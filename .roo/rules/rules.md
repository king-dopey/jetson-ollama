# Workspace layout

Filesystem tools are served by a containerized MCP server that mounts the repository
at /projects. When using read_file, write_to_file, list_files, search_files, or any
other filesystem tool, **always prefix paths with /projects/**, e.g.:

  - The README at the repo root is /projects/README.md
  - The new llmrouter subproject lives at /projects/router/

Shell commands run via execute_command, however, run in the host workspace's
working directory and use repo-relative paths (e.g. `ls router/`). Do not
prefix shell command paths with /projects/.

If a tool returns a "path not found" or "outside allowed directory" error, the
first thing to check is whether you forgot the /projects/ prefix on a filesystem
tool, or wrongly added it to a shell command.