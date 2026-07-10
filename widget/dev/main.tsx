/* Local dev harness: renders the real widget against the simulator stack.

   Prereqs: `docker compose up -d` in simulators/ (agent on :49100), then
   `npm run dev` here and open the printed URL. */
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import PumpAnalysisWidget from "../src/PumpAnalysisWidget";

const queryClient = new QueryClient();

const rootEl = document.createElement("div");
rootEl.style.maxWidth = "720px";
rootEl.style.margin = "2rem auto";
rootEl.style.padding = "0 1rem";
document.body.appendChild(rootEl);

createRoot(rootEl).render(
  <QueryClientProvider client={queryClient}>
    <PumpAnalysisWidget uiElement={{ app_key: "test_app_key" }} />
  </QueryClientProvider>
);
