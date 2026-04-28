// craco.config.js — minimal config for the dashboard frontend.
const path = require("path");
require("dotenv").config();

module.exports = {
    eslint: {
        configure: {
            extends: ["plugin:react-hooks/recommended"],
            rules: {
                "react-hooks/rules-of-hooks": "error",
                "react-hooks/exhaustive-deps": "warn",
            },
        },
    },
    webpack: {
        alias: {
            "@": path.resolve(__dirname, "src"),
        },
        configure: (cfg) => {
            cfg.watchOptions = {
                ...cfg.watchOptions,
                ignored: [
                    "**/node_modules/**",
                    "**/.git/**",
                    "**/build/**",
                    "**/dist/**",
                    "**/coverage/**",
                    "**/public/**",
                ],
            };
            return cfg;
        },
    },
};
