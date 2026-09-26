import { spawnSync } from "node:child_process";

const watched = new Set(["bash", "edit", "write", "apply_patch", "patch"]);

export const DDTmuxEditCapture = async ({ directory }) => {
  const capture = (phase, input, output) => {
    if (!watched.has(input.tool)) return;
    const payload = {
      cwd: directory,
      session_id: input.sessionID,
      tool_use_id: input.callID,
      tool_name: input.tool,
      tool_input: input.args || output?.args || {},
    };
    spawnSync(process.env.DD_TMUX_CAPTURE_PYTHON || "python3",
      [process.env.DD_TMUX_CAPTURE_HOOK, phase, "opencode"], {
      input: JSON.stringify(payload),
      env: process.env,
      stdio: ["pipe", "ignore", "ignore"],
      timeout: 15000,
    });
  };
  return {
    "tool.execute.before": (input, output) => capture("pre", input, output),
    "tool.execute.after": (input, output) => capture("post", input, output),
  };
};
