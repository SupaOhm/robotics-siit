# Contributing

## Workflow

1. Pull the latest `main`.
2. Make a branch named `lane<N>/<short-topic>`, for example
   `lane2/yolo-detector` or `lane4/telegram-bot`.
3. Commit small, working steps.
4. Push and open a pull request into `main`. Fill in the template.
5. One teammate approves, and CI passes. Then merge it yourself.

```bash
git checkout main && git pull
git checkout -b lane2/yolo-detector
# ... work ...
git push -u origin lane2/yolo-detector
gh pr create        # or open the PR on github.com
```

`main` is protected: nobody pushes to it directly, and it must always build.

## Where your code goes

- One ROS 2 package per module, in `src/<package_name>/`. Your lane creates
  and owns it. Copy the structure of `src/password_system`
  (`package.xml`, `setup.py`, `setup.cfg`, `resource/`, `config/`,
  `launch/`, `test/`).
- Only edit another lane's package after you agree it with that lane, and
  tag them on the PR.
- Benchmarks and one-off scripts go in `tools/`, and CoppeliaSim scenes in
  `sim/`.

## Interfaces

Lane 1 keeps the list of topics and message types in `docs/interfaces.md`.
If your PR adds, renames or changes a topic, update that file in the same PR
and tag Lane 1.

## Don't commit

- **Secrets.** The Telegram bot token and chat id belong in environment
  variables or a local `.env` file, which is gitignored.
- **Model weights.** For YOLO `.pt` / `.onnx` / NCNN files, add a download
  step in the package README instead.
- Large videos or recordings. Share them on the team drive.

Short audio clips (`.wav` / `.mp3`, a few hundred KB) are fine to commit.

## Tests

Put tests in `src/<package>/test/`. CI runs `pytest` in every package that
has a `test/` folder, so keep the tests free of ROS and of hardware (see
`password_system/test`).
