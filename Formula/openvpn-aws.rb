class OpenvpnAws < Formula
  desc "OpenVPN with raised buffers for AWS Client VPN SAML federation"
  homepage "https://github.com/TakiTake/openvpn-aws"
  url "https://github.com/TakiTake/openvpn-aws/releases/download/v2.7.5-0/openvpn-aws-v2.7.5-0-aarch64-apple-darwin.tar.gz"
  sha256 "67a7886176378e619b311f837163bbd7326d622f710349d0709688ffc7732930"
  license "GPL-2.0-only"

  depends_on arch: :arm64
  depends_on :macos

  # Prebuilt on GitHub Actions (see the openvpn-aws repo): stock OpenVPN
  # with a 3-define buffer patch — AWS transports the multi-KB SAML
  # response as the password inside one TLS control message, which stock
  # OpenVPN caps at 2 KB (upstream rejected raising it: openvpn#295).
  # OpenSSL is statically linked, so no runtime deps. Each release also
  # carries the corresponding patched source (GPLv2).
  def install
    bin.install "openvpn-aws"
    prefix.install "COPYING", "aws-buffers.patch"
  end

  test do
    assert_match "OpenVPN #{version}", shell_output("#{bin}/openvpn-aws --version")
  end
end
