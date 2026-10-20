// ESLint flat config, run with plain `eslint` (`next lint` is deprecated in
// Next 15.5 and removed in 16). FlatCompat loads Next's shareable config,
// the same rule set the old .eslintrc.json extended.
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...compat.extends("next/core-web-vitals"),
];

export default config;
