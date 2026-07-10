/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{ts,tsx}"],
  // Scope everything under the widget root so utilities can't leak into the
  // host page (the bundle's CSS is injected into the host document).
  important: ".paw-root",
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--paw-border))",
        background: "hsl(var(--paw-background))",
        foreground: "hsl(var(--paw-foreground))",
        card: "hsl(var(--paw-card))",
        "card-foreground": "hsl(var(--paw-card-foreground))",
        muted: "hsl(var(--paw-muted))",
        "muted-foreground": "hsl(var(--paw-muted-foreground))",
        primary: "hsl(var(--paw-primary))",
        "primary-foreground": "hsl(var(--paw-primary-foreground))",
        destructive: "hsl(var(--paw-destructive))",
        warning: "hsl(var(--paw-warning))",
        success: "hsl(var(--paw-success))",
      },
      borderRadius: {
        lg: "0.5rem",
        xl: "0.75rem",
      },
    },
  },
  plugins: [],
};
