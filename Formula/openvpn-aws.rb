class OpenvpnAws < Formula
  desc "OpenVPN with raised buffers for AWS Client VPN SAML federation"
  homepage "https://github.com/TakiTake/vpnp"
  url "https://swupdate.openvpn.org/community/releases/openvpn-2.7.5.tar.gz"
  sha256 "c6864b3c7d4e059c7d6ce22d1b5fa646c8b379a06af872eeb9792b6083a44ac4"
  license "GPL-2.0-only"

  depends_on "pkgconf" => :build
  depends_on "lz4"
  depends_on "lzo"
  depends_on :macos
  depends_on "openssl@3"
  depends_on "pkcs11-helper"

  # AWS Client VPN SAML federation sends the multi-KB SAML response as the
  # OpenVPN password inside a single TLS control-channel message; stock
  # buffers cap that at 2 KB. Same approach as the AWS-official client and
  # samm-git/aws-vpn-client, rebased onto 2.7.5. Used by vpnp for
  # auth-federate profiles; installed as `openvpn-aws`, so it never
  # conflicts with stock openvpn.
  patch :DATA

  def install
    system "./configure", "--disable-debug",
                          "--disable-silent-rules",
                          "--with-crypto-library=openssl",
                          "--enable-pkcs11",
                          "--prefix=#{prefix}"
    system "make"
    bin.install "src/openvpn/openvpn" => "openvpn-aws"
  end

  test do
    assert_match "OpenVPN 2.7.5", shell_output("#{bin}/openvpn-aws --version")
  end
end

__END__
diff -ur a/src/openvpn/common.h b/src/openvpn/common.h
--- a/src/openvpn/common.h	2026-07-25 17:36:20
+++ b/src/openvpn/common.h	2026-07-25 17:36:20
@@ -67,7 +67,7 @@
  * maximum size of a single TLS message (cleartext).
  * This parameter must be >= PUSH_BUNDLE_SIZE
  */
-#define TLS_CHANNEL_BUF_SIZE 2048
+#define TLS_CHANNEL_BUF_SIZE (256 * 1024)
 
 /* TLS control buffer minimum size
  *
diff -ur a/src/openvpn/error.h b/src/openvpn/error.h
--- a/src/openvpn/error.h	2026-07-25 17:36:20
+++ b/src/openvpn/error.h	2026-07-25 17:36:20
@@ -31,9 +31,9 @@
 /* #define ABORT_ON_ERROR */
 
 #if defined(ENABLE_PKCS11) || defined(ENABLE_MANAGEMENT)
-#define ERR_BUF_SIZE 10240
+#define ERR_BUF_SIZE (256 * 1024)
 #else
-#define ERR_BUF_SIZE 1280
+#define ERR_BUF_SIZE (256 * 1024)
 #endif
 
 struct gc_arena;
diff -ur a/src/openvpn/misc.h b/src/openvpn/misc.h
--- a/src/openvpn/misc.h	2026-07-25 17:36:20
+++ b/src/openvpn/misc.h	2026-07-25 17:36:20
@@ -62,9 +62,9 @@
 
 /* max length of username/password */
 #ifdef ENABLE_PKCS11
-#define USER_PASS_LEN 4096
+#define USER_PASS_LEN (128 * 1024)
 #else
-#define USER_PASS_LEN 128
+#define USER_PASS_LEN (128 * 1024)
 #endif
     /* Note that username and password are expected to be null-terminated */
     char username[USER_PASS_LEN];
