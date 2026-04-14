---
trigger: always_on
glob: "**/*.{py,js,html,css,md}"
description: Rule for stateful development by maintaining context files in the CONTEXT/ directory.
---

# Context Management Rule

To maintain systemic project knowledge, follow this workflow for EVERY feature modification or new implementation:

1. **Check Context**: Before editing or creating any feature-related code, you MUST search for and read the relevant context file in the `CONTEXT/` directory.
2. **Execute Feature**: Implement the changes or create the new feature.
3. **Synchronize Context**: Immediately after the implementation, update the corresponding context file in `CONTEXT/` to reflect the changes. Focus on recording only the **most relevant** updates to keep the documentation concise.
4. **Auto-Initialization**: If NO relevant context file exists for a new feature or an existing one, you MUST create a new documentation file in the `CONTEXT/` directory. Keep the documentation **minimal and focused**, capturing only the essential logic, architecture, and usage to avoid bloat.

Failure to maintain the context files in the `CONTEXT/` directory is a violation of the project's development protocol. Always ensure the "Context Loop" (Read → Edit → Update) is closed.
