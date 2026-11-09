// Tailwind v4 — same PostCSS entry point as customer-site (@tailwindcss/postcss
// handles vendor prefixing itself, so no autoprefixer). v3's `--tw-*` universal
// defaults hack lived here: v4 registers those as @property instead, so the
// host's own v4 utilities are no longer clobbered by our bundle.
module.exports = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
