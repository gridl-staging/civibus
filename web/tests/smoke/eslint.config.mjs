// ESLint flat config for browser tests — enforces human-like interaction patterns.
// See BROWSER_TESTING_STANDARDS__3.md for rationale. Do not weaken these rules.
import playwright from "eslint-plugin-playwright";
import tseslint from "typescript-eslint";

export default [
  {
    ...playwright.configs["flat/recommended"],
    files: ["**/*.spec.ts"],
    languageOptions: {
      parser: tseslint.parser
    },
    rules: {
      ...playwright.configs["flat/recommended"].rules,
      "playwright/no-eval": "error",
      "playwright/no-raw-locators": [
        "error",
        {
          allowed: [
            "aside",
            "tr",
            "main",
            "option",
            'meta[name="description"]',
            'meta[property="og:title"]',
            'meta[property="og:description"]',
            'meta[property="og:type"]',
            'meta[property="og:url"]',
            'meta[property="og:image"]',
            'meta[property="og:site_name"]',
            'meta[name="twitter:card"]',
            'meta[name="twitter:title"]',
            'meta[name="twitter:description"]',
            'meta[name="twitter:image"]',
            'link[rel="canonical"]',
            'script[type="application/ld+json"]'
          ]
        }
      ],
      "playwright/prefer-native-locators": "error",
      "playwright/no-element-handle": "error",
      "playwright/no-page-pause": "error",
      "playwright/no-force-option": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[object.name='request']",
          message: "API calls not allowed in spec files. Move to fixtures.ts."
        },
        {
          selector: "MemberExpression[property.name='evaluate']",
          message: "page.evaluate() not allowed in spec files."
        },
        {
          selector: "CallExpression[callee.property.name='waitForTimeout']",
          message: "Arbitrary waits not allowed. Use Playwright auto-waiting."
        },
        {
          selector: "CallExpression[callee.name='setTimeout']",
          message: "setTimeout not allowed in spec files. Use deterministic route/listener gating."
        },
        {
          selector: "CallExpression[callee.property.name='dispatchEvent']",
          message: "Synthetic events not allowed. Use real user interactions."
        },
        {
          selector: "CallExpression[callee.property.name='setExtraHTTPHeaders']",
          message: "setExtraHTTPHeaders not allowed in spec files."
        }
      ]
    }
  }
];
