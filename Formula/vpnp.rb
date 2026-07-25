class Vpnp < Formula
  desc "AWS Client VPN on macOS without breaking apple/container"
  homepage "https://github.com/TakiTake/vpnp"
  url "https://github.com/TakiTake/vpnp/releases/download/v0.1.0/vpnp-v0.1.0-aarch64-apple-darwin.tar.gz"
  sha256 "2a29b3fef879e45ef68242586c3e08b3de11cdf507dc2d2491d5ced805106aae"
  license "MIT"

  depends_on arch: :arm64
  depends_on :macos
  depends_on "openvpn"

  def install
    bin.install "vpnp"
    (etc/"vpnp").install ".env.example"
    (etc/"vpnp/config").install "config/vpn.dns.example",
                                "config/vpn.access.example",
                                "config/README.md"
  end

  def caveats
    <<~EOS
      Put your AWS Client VPN profile (mutual-certificate auth) at:
        #{etc}/vpnp/config/vpn.ovpn
      then connect with:
        vpnp up
      Config and logs live under #{etc}/vpnp.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/vpnp version")
  end
end
