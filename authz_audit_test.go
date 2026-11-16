package svn

// Tests use only temporary files and the official local svnauthz executable.
import (
    "os"
    "os/exec"
    "path/filepath"
    "strings"
    "testing"

    "svnadmin/internal/config"
)

func auditLoad(t *testing.T, content string) *Authz {
    t.Helper()
    cfg := config.Default()
    cfg.SVN.HomePath = t.TempDir()
    if err := os.WriteFile(cfg.SVN.AuthzFile(), []byte(content), 0600); err != nil { t.Fatal(err) }
    a, err := LoadAuthz()
    if err != nil { t.Fatal(err) }
    return a
}

func TestAuditSVNOracle(t *testing.T) {
    cases := []struct { name, text, path, user string }{
        {"direct_allow", "[repo:/]\nalice = rw\n", "/", "alice"},
        {"explicit_child_deny", "[repo:/]\nalice = rw\n[repo:/secret]\nalice =\n", "/secret", "alice"},
        {"wildcard_then_named_allow", "[repo:/]\n* =\nalice = rw\n", "/", "alice"},
        {"union_of_groups", "[groups]\nreaders=alice\nwriters=alice\n[repo:/]\n@readers=r\n@writers=rw\n", "/", "alice"},
        {"nested_group_parent", "[groups]\nchild=alice\nparent=@child\n[repo:/]\n@parent=rw\n", "/", "alice"},
        {"nested_group_not_reverse", "[groups]\nchild=bob\nparent=alice,@child\n[repo:/]\n@child=rw\n", "/", "alice"},
        {"alias_identity", "[aliases]\nowner=alice\n[repo:/]\n&owner=rw\n", "/", "bob"},
        {"child_section_without_user", "[repo:/]\nalice=rw\n[repo:/secret]\nbob=rw\n", "/secret", "alice"},
        {"global_specific_path", "[repo:/]\nalice=rw\n[/secret]\nalice=\n", "/secret", "alice"},
    }
    for _, tc := range cases {
        t.Run(tc.name, func(t *testing.T) {
            a := auditLoad(t, tc.text)
            output, err := exec.Command("svnauthz", "accessof", "--username", tc.user,
                "--repository", "repo", "--path", tc.path, a.Path).CombinedOutput()
            if err != nil { t.Fatalf("official svnauthz could not evaluate fixture: %v %s", err, output) }
            want := strings.TrimSpace(string(output)); if want == "no" { want = "" }
            got := a.EffectivePerm("repo", tc.path, tc.user)
            t.Logf("official=%q panel=%q", want, got)
            if got != want { t.Errorf("permission decision differs from Subversion") }
        })
    }
}

func TestAuditCaseSensitivePathEdits(t *testing.T) {
    a := auditLoad(t, "[repo:/Secret]\nalice=r\n")
    a.SetPathPri("repo", "/secret", "alice", "rw", false)
    if err := a.Save(); err != nil { t.Fatal(err) }
    output, err := exec.Command("svnauthz", "accessof", "--username", "alice",
        "--repository", "repo", "--path", "/Secret", a.Path).CombinedOutput()
    if err != nil { t.Fatal(err) }
    if strings.TrimSpace(string(output)) != "r" {
        t.Errorf("editing /secret changed /Secret: official=%q", strings.TrimSpace(string(output)))
    }
}

func TestAuditInterleavedAuthzWrites(t *testing.T) {
    first := auditLoad(t, "[repo:/]\nseed=r\n")
    second, err := LoadAuthz(); if err != nil { t.Fatal(err) }
    first.SetPathPri("repo", "/", "alice", "r", false)
    second.SetPathPri("repo", "/", "bob", "r", false)
    if err = first.Save(); err != nil { t.Fatal(err) }
    if err = second.Save(); err != nil { t.Fatal(err) }
    got, err := os.ReadFile(filepath.Clean(first.Path)); if err != nil { t.Fatal(err) }
    if !strings.Contains(string(got), "alice = r") { t.Error("one successful write was lost by a second loaded instance") }
}
