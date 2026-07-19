import { dirname } from "path";
import { fileURLToPath } from "url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    ignores: [".next/**", "node_modules/**"],
  },
  /*
   * S2 additions per docs/solution/06:
   * - no-literal-strings in JSX (allowlist for clinical codes/units) — §9
   * - ban `!important` and raw palette utilities (bg-white, text-gray-*) — §4.2
   * - dependency lint: packages/ui must stay presentational (no ts-sdk
   *   imports); hand-written fetch banned outside the two BFF routes — §8
   */
];

export default eslintConfig;
