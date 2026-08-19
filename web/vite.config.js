import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Published at https://s155003.github.io/gridshift/, so assets need that prefix.
// `npm run dev` serves from / locally, which is why base is conditional.
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/gridshift/" : "/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // model.json is 614KB of tree nodes. Keeping it a separate fetched asset
    // rather than inlining it means the shell paints before the model lands.
    assetsInlineLimit: 4096,
  },
}));
