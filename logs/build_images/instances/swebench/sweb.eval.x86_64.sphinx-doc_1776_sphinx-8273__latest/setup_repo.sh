#!/bin/bash
set -euxo pipefail
git clone -o origin  --single-branch https://github.com/sphinx-doc/sphinx /testbed
chmod -R 777 /testbed
cd /testbed
git reset --hard 88b81a06eb635a1596617f8971fa97a84c069e93
git remote remove origin
TARGET_TIMESTAMP=$(git show -s --format=%ci 88b81a06eb635a1596617f8971fa97a84c069e93)
git tag -l | while read tag; do TAG_COMMIT=$(git rev-list -n 1 "$tag"); TAG_TIME=$(git show -s --format=%ci "$TAG_COMMIT"); if [[ "$TAG_TIME" > "$TARGET_TIMESTAMP" ]]; then git tag -d "$tag"; fi; done
git reflog expire --expire=now --all
git gc --prune=now --aggressive
AFTER_TIMESTAMP=$(date -d "$TARGET_TIMESTAMP + 1 second" '+%Y-%m-%d %H:%M:%S')
COMMIT_COUNT=$(git log --oneline --all --since="$AFTER_TIMESTAMP" | wc -l)
[ "$COMMIT_COUNT" -eq 0 ] || exit 1
source /opt/miniconda3/bin/activate
conda activate testbed
echo "Current environment: $CONDA_DEFAULT_ENV"
sed -i 's/pytest/pytest -rA/' tox.ini
sed -i 's/Jinja2>=2.3/Jinja2<3.0/' setup.py
sed -i 's/sphinxcontrib-applehelp/sphinxcontrib-applehelp<=1.0.7/' setup.py
sed -i 's/sphinxcontrib-devhelp/sphinxcontrib-devhelp<=1.0.5/' setup.py
sed -i 's/sphinxcontrib-qthelp/sphinxcontrib-qthelp<=1.0.6/' setup.py
sed -i 's/alabaster>=0.7,<0.8/alabaster>=0.7,<0.7.12/' setup.py
sed -i "s/'packaging',/'packaging', 'markupsafe<=2.0.1',/" setup.py
sed -i 's/sphinxcontrib-htmlhelp/sphinxcontrib-htmlhelp<=2.0.4/' setup.py
sed -i 's/sphinxcontrib-serializinghtml/sphinxcontrib-serializinghtml<=1.1.9/' setup.py
python -m pip install -e .[test]
git config --global user.email setup@swebench.config
git config --global user.name SWE-bench
git commit --allow-empty -am SWE-bench
