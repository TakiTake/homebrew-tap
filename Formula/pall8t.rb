class Pall8t < Formula
  desc "Run AI coding agents in apple/container sandboxes"
  homepage "https://github.com/TakiTake/pall8t"
  url "https://github.com/TakiTake/pall8t/releases/download/v0.1.0/pall8t-v0.1.0-aarch64-apple-darwin.tar.gz"
  sha256 "f170851b0605e30e4e0dd947e39df88c430e05a3bb7803bf542e93555e1f0e05"
  license "MIT"

  depends_on :macos
  depends_on arch: :arm64

  def install
    bin.install "pall8t"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/pall8t --version")
  end
end
