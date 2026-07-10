/* Dev shim for `customer_site/useRemoteParams` — the local device agent
   always runs as agent "1" (AGENT_ID in simulators/docker-compose.yml). */
export function useRemoteParams(): Record<string, string | undefined> {
  return { agentId: "1" };
}
