class Pall8t < Formula
  desc "Run AI coding agents in apple/container sandboxes"
  homepage "https://github.com/TakiTake/pall8t"
  url "https://github.com/TakiTake/pall8t/releases/download/v0.3.0/pall8t-v0.3.0-aarch64-apple-darwin.tar.gz"
  sha256 "7080d0ef166b31ec7d54915ffd1772ed09534b5437e7321a2daf773734d2f593"
  license "MIT"

  depends_on arch: :arm64
  depends_on :macos

  def install
    bin.install "pall8t"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pall8t --version")
  end
end
