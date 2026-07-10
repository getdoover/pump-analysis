/* Dev-harness build: renders the widget standalone in a browser against the
   local simulator stack. No Module Federation — the host-provided modules
   (customer_site/*, doover-js) are aliased to shims in dev/shims/.

   Usage: npm run dev  (simulator stack must be up; agent API on :49100) */
import path from "node:path";
import { defineConfig } from "@rsbuild/core";
import { pluginReact } from "@rsbuild/plugin-react";

export default defineConfig({
  source: {
    entry: { index: "./dev/main.tsx" },
  },
  resolve: {
    alias: {
      "customer_site/RemoteComponentWrapper": path.resolve(
        __dirname,
        "dev/shims/customer-site-wrapper.tsx"
      ),
      "customer_site/useRemoteParams": path.resolve(
        __dirname,
        "dev/shims/customer-site-params.ts"
      ),
      "doover-js/react": path.resolve(__dirname, "dev/shims/doover-js-react.ts"),
      "doover-js$": path.resolve(__dirname, "dev/shims/doover-js.ts"),
    },
  },
  server: {
    port: 8007,
    proxy: {
      "/dda": {
        target: "https://localhost:49100",
        changeOrigin: true,
        secure: false, // local agent uses a self-signed cert
        pathRewrite: { "^/dda": "" },
      },
    },
  },
  html: {
    title: "Pump Analysis Widget — local dev",
  },
  plugins: [pluginReact()],
});
