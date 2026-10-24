"""Test and maintenance helpers shipped with the Xu source tree.

Keeping ``scripts`` as an explicit package makes helpers such as
``prove_no_syscalls`` importable when pytest is run from either the repository
root or the ``xu`` directory (and avoids collisions with unrelated installed
namespace packages named ``scripts``).
"""
