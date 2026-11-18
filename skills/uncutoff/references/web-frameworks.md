# Web Frameworks Reference

## Tailwind CSS v4 (`tailwindcss >= 4`)

- **CUT-040 (`@tailwind` directives)**:
  - **Avoid**: `@tailwind base;`, `@tailwind components;`, `@tailwind utilities;`
  - **Use**: `@import "tailwindcss";` and `@theme { --color-brand: #2563eb; }`
- **CUT-041 (`tailwind.config.*` ignored by default)**:
  - Tailwind v4 does not load `tailwind.config.js` / `.ts` automatically. Migrate theme tokens to CSS `@theme { ... }`, or explicitly add `@config "../tailwind.config.ts";` if needed.

## Next.js 15+ (`next >= 15`)

- **CUT-050 (Async Request APIs)**:
  - **Avoid**: `const c = cookies().get("theme")` or `headers().get("host")`
  - **Use**: `const cookieStore = await cookies();` / `const headerList = await headers();` inside `async` Server Components, Route Handlers, or Server Actions.

## React 19 (`react >= 19`)

- **CUT-060 (`useFormState` renamed)**:
  - **Avoid**: `import { useFormState } from "react-dom"`
  - **Use**: `import { useActionState } from "react"`

## Svelte 5 (`svelte >= 5`)

- **CUT-070 (Runes migration)**:
  - **Avoid**: `export let propName`, `$: derived = ...`, and `createEventDispatcher()` in Svelte 5 components
  - **Use**: `let { propName } = $props()`, `const derived = $derived(...)`, `$effect(...)`, and callback props (`onsubmit`, `onchange`).

## Zod v4 (`zod >= 4`)

- **CUT-080 (Removed/changed Zod v3 APIs)**:
  - **Avoid**: `z.nativeEnum(MyEnum)` and `{ invalid_type_error: ..., required_error: ... }`
  - **Use**: `z.enum(MyEnum)` and `{ error: (iss) => ... }`

## ESLint v9 (`eslint >= 9`)

- **CUT-090 (Flat config)**:
  - **Avoid**: `.eslintrc`, `.eslintrc.json`, `.eslintrc.js`, `.eslintignore`
  - **Use**: `eslint.config.js` or `eslint.config.mjs` exporting a flat config array (with `ignores: [...]`).
