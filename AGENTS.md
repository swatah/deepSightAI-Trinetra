# Agent Guidelines for deepSightAI-Trinetra

## MANDATORY PRE-EXECUTION REQUIREMENT
Before writing, creating, modifying, or refactoring ANY code in this repository:
1. You **MUST** read and strictly follow [CODING_STANDARDS.md](file:///home/abhinav/ml/deepSightAI-Trinetra/CODING_STANDARDS.md).
2. All packages and microservice directories **MUST** follow PascalCase/CamelCase under `deepSightAI/Trinetra/`:
   - `deepSightAI/Trinetra/ServerAndExtractor/`
   - `deepSightAI/Trinetra/AuthService/`
   - `deepSightAI/Trinetra/SearchService/`
   - `deepSightAI/Trinetra/Embedder/`
   - `deepSightAI/Trinetra/AuditService/`
   - `deepSightAI/Trinetra/Shared/`
   - `deepSightAI/Trinetra/UI/`
3. All imports **MUST** use canonical paths (`from deepSightAI.Trinetra.Shared...`). Legacy `from shared...` or `from Shared...` are strictly forbidden.
4. **NO SYMLINKS** (`ln -s`), **NO `sys.path.insert`**, and **NO `PYTHONPATH` hacks** are permitted. Package resolution must occur natively via standard package installation (`pip install -e .`).
5. All Dockerfiles and docker-compose files must use root build context (`context: ../../..` from subdirectories) and correct paths under `deepSightAI/Trinetra/`.
6. All variable names, module/script file names, and function/method names **MUST** start with the `dsai_` prefix (e.g. `dsai_<name>`).
7. Run relevant test suites before marking tasks as complete.
