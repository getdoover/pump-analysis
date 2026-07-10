/* Dev shim for `customer_site/RemoteComponentWrapper` — plain passthrough. */
import type { ReactNode } from "react";

export default function RemoteComponentWrapper({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
