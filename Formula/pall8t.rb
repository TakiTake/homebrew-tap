class Pall8t < Formula
  desc "Run AI coding agents in apple/container sandboxes"
  homepage "https://github.com/TakiTake/pall8t"
  url "https://github.com/TakiTake/pall8t/releases/download/v0.4.0/pall8t-v0.4.0-aarch64-apple-darwin.tar.gz"
  sha256 "1b84a08bc027be11a878a5405eb5f08e38dd78065906ff9346d0f0577a02f061"
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
