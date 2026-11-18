"""Read-only retrieval diagnostic for the STIF Campus AI backend.

Run ``python -m diagnostics --help``. It inspects the college index files that the
backend would serve, runs sample questions through legacy and improved retrieval,
and checks what would be sent to the LLM - without writing to any index, reading
``.env`` secrets (unless ``--use-env``) or using the network.
"""

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_USAGE = 3
