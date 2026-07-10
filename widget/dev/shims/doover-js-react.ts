/* Dev shims for `doover-js/react`, backed by the local device agent's data
   API (proxied at /dda -> https://localhost:49100).

   - useAgentChannel("tag_values") polls the live aggregate every 2 s.
   - useAgentChannel("deployment_config") returns a synthesized config built
     from simulators/app_config.json (the local agent's channel is empty —
     config reaches the app via CONFIG_FP, not the channel).
   - useDooverClient().messages.getTimeseries returns no history: the local
     agent has no timeseries endpoint, so the trail/NPSH-history views stay
     empty in the harness.
*/
import { useEffect, useState } from "react";

// Injected at app start via CONFIG_FP in the simulator stack.
import simConfig from "../../../simulators/app_config.json";

const APP_KEY = "test_app_key";
const POLL_MS = 2000;
const HISTORY_CAP = 1800; // ~1 h of 2 s samples

// The local agent has no timeseries endpoint, so the tag_values poller
// buffers samples in memory and getTimeseries serves them back — the
// trail/NPSH-history views fill up while the page is open.
const history: Array<{ timestamp: string; value: Record<string, unknown> }> = [];

export function useAgentChannel<T>(
  agentId: string | undefined,
  channelName: string
): { data: T | undefined; isLoading: boolean } {
  const [data, setData] = useState<T | undefined>(undefined);

  useEffect(() => {
    if (!agentId) return;

    if (channelName === "deployment_config") {
      setData({ applications: { [APP_KEY]: simConfig } } as T);
      return;
    }

    let alive = true;
    const poll = async () => {
      try {
        const res = await fetch(`/dda/ch/v1/agent/${agentId}/${channelName}/aggregate`);
        if (!res.ok) return;
        const body = await res.json();
        const payload = body?.aggregate?.payload;
        if (channelName === "tag_values" && payload) {
          history.push({ timestamp: new Date().toISOString(), value: payload });
          if (history.length > HISTORY_CAP) history.shift();
        }
        if (alive) setData(payload as T);
      } catch {
        /* agent not up yet — keep polling */
      }
    };
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [agentId, channelName]);

  return { data, isLoading: data === undefined };
}

export function useDooverClient() {
  return {
    messages: {
      getTimeseries: async () => ({ results: [...history], next: null }),
    },
  };
}
