class GitCleaner < Formula
  desc "CLI tool to automatically manage your GitHub followers and following lists"
  homepage "https://github.com/Jamkris/git-cleaner"
  url "https://github.com/Jamkris/git-cleaner/archive/refs/tags/v1.0.0.tar.gz"
  sha256 "REPLACE_WITH_ACTUAL_SHA256_AFTER_RELEASE"
  license "MIT"

  depends_on "python@3.12"

  def install
    # Install the bash entry point
    bin.install "git-cleaner"

    # Install the Python core + requirements to libexec
    libexec.install "githubapi.py"
    libexec.install "requirements.txt"

    # Point the wrapper at the libexec copies
    inreplace bin/"git-cleaner", "$SCRIPT_DIR/githubapi.py", "#{libexec}/githubapi.py"
    inreplace bin/"git-cleaner", "$SCRIPT_DIR/requirements.txt", "#{libexec}/requirements.txt"
  end

  test do
    assert_match "git-cleaner", shell_output("#{bin}/git-cleaner -h")
    assert_match "en", shell_output("GIT_CLEANER_LANG=en #{bin}/git-cleaner lang")
    assert_match "ko", shell_output("GIT_CLEANER_LANG=ko #{bin}/git-cleaner lang")
  end
end
