// An arm64 Mac refuses to start an app whose signature is broken: sign the whole bundle ad hoc (no developer account needed)
const { execFileSync } = require("child_process");
const path = require("path");

exports.default = async function (context) {
  if (context.electronPlatformName !== "darwin") return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  execFileSync("codesign", ["--force", "--deep", "--sign", "-", app], { stdio: "inherit" });
};
