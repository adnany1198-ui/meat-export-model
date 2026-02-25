mkdir -p ~/meat-export-model/reference
pbpaste > ~/meat-export-model/reference/VALIDATION_REPORT.GS
git -C ~/meat-export-model add reference/
git -C ~/meat-export-model pull
git -C ~/meat-export-model add reference/
git -C ~/meat-export-model commit -m "Add GAS source as reference"
git -C ~/meat-export-model push origin claude/setup-safi-engine-project-jk1CO