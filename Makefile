# LLM Code and Review Tools - Makefile
#
# Targets:
#   make install   - Install all tools (jira, gerrit-comments, beads)
#   make uninstall - Uninstall all tools
#   make help      - Show this help
#

.PHONY: install uninstall help

help:
	@echo "LLM Code and Review Tools"
	@echo ""
	@echo "Usage:"
	@echo "  make install    Install all tools (jira, gerrit-comments, beads)"
	@echo "  make uninstall  Uninstall all tools"
	@echo "  make help       Show this help"
	@echo ""

install:
	@./install.sh

uninstall:
	@./install.sh --uninstall
