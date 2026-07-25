class Vpnp < Formula
  desc "AWS Client VPN on macOS without breaking apple/container"
  homepage "https://github.com/TakiTake/vpnp"
  url "https://github.com/TakiTake/vpnp/releases/download/v0.2.0/vpnp-v0.2.0-aarch64-apple-darwin.tar.gz"
  sha256 "467305b1d06db85c123223f561172e976f8d054b88768e3e0d4c9dde12285981"
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
