class Pall8t < Formula
  desc "Run AI coding agents in apple/container sandboxes"
  homepage "https://github.com/TakiTake/pall8t"
  url "https://github.com/TakiTake/pall8t/releases/download/v0.2.0/pall8t-v0.2.0-aarch64-apple-darwin.tar.gz"
  sha256 "b0b2b8529001945f2509eee57cf2e1d6527eb1ab0dc6b855942107b89fd3a008"
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
