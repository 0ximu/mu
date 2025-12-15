# typed: false
# frozen_string_literal: true

class Mu < Formula
  desc "Machine Understanding - Semantic compression for AI-native development"
  homepage "https://github.com/0ximu/mu"
  version "0.0.1"
  license "Apache-2.0"

  # Binary downloads from GitHub releases
  on_macos do
    on_arm do
      url "https://github.com/0ximu/mu/releases/download/v#{version}/mu-macos-arm64"
      sha256 "PLACEHOLDER_SHA256_MACOS_ARM64"
    end
    on_intel do
      url "https://github.com/0ximu/mu/releases/download/v#{version}/mu-macos-x86_64"
      sha256 "PLACEHOLDER_SHA256_MACOS_X86_64"
    end
  end

  on_linux do
    on_arm do
      url "https://github.com/0ximu/mu/releases/download/v#{version}/mu-linux-arm64"
      sha256 "PLACEHOLDER_SHA256_LINUX_ARM64"
    end
    on_intel do
      url "https://github.com/0ximu/mu/releases/download/v#{version}/mu-linux-x86_64"
      sha256 "PLACEHOLDER_SHA256_LINUX_X86_64"
    end
  end

  def install
    binary_name = stable.url.split("/").last
    bin.install binary_name => "mu"
  end

  test do
    assert_match "mu, version #{version}", shell_output("#{bin}/mu --version")
  end
end
