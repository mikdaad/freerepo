/**
 * Minimal assertion harness for the Node verification scripts.
 *
 * Deliberately dependency-free: `node --test` or Vitest would work, but a zero-dependency script
 * means `npm run verify:db` runs on a clean checkout with nothing but `tsx` installed, which is
 * exactly when you want it to run (e.g. in a pre-commit hook or a CI container).
 */

interface Failure {
  readonly label: string;
  readonly detail?: string;
}

const failures: Failure[] = [];
let assertions = 0;

const COLOR = {
  reset: '\u001b[0m',
  dim: '\u001b[2m',
  green: '\u001b[32m',
  red: '\u001b[31m',
  cyan: '\u001b[36m',
  yellow: '\u001b[33m',
};

export function announceSection(title: string): void {
  process.stdout.write(`\n${COLOR.cyan}▸ ${title}${COLOR.reset}\n`);
}

/** Records a pass/fail. Never throws, so one bad assertion does not hide the rest. */
export function check(label: string, condition: boolean, detail?: string): void {
  assertions += 1;
  if (condition) {
    process.stdout.write(`  ${COLOR.green}✓${COLOR.reset} ${label}\n`);
    return;
  }
  failures.push(detail === undefined ? { label } : { label, detail });
  process.stdout.write(
    `  ${COLOR.red}✗ ${label}${COLOR.reset}${detail === undefined ? '' : ` ${COLOR.dim}(${detail})${COLOR.reset}`}\n`,
  );
}

/** Prints the summary and sets the process exit code. */
export function finish(): void {
  const passed = assertions - failures.length;
  process.stdout.write(
    `\n${failures.length === 0 ? COLOR.green : COLOR.red}${passed}/${assertions} checks passed${COLOR.reset}\n`,
  );

  if (failures.length > 0) {
    process.stdout.write(`${COLOR.red}Failures:${COLOR.reset}\n`);
    for (const failure of failures) {
      process.stdout.write(`  • ${failure.label}${failure.detail ? ` — ${failure.detail}` : ''}\n`);
    }
    process.exitCode = 1;
    return;
  }

  process.stdout.write(`${COLOR.green}All Phase 2 invariants hold.${COLOR.reset}\n`);
}

/**
 * Runs an async scenario, converting an unexpected throw into a failure report.
 * A crashed scenario must still print the assertions that already ran.
 */
export function run(scenario: () => Promise<void>): void {
  scenario().catch((error: unknown) => {
    process.stdout.write(
      `\n${COLOR.red}Harness crashed:${COLOR.reset} ${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`,
    );
    failures.push({
      label: 'harness completed without throwing',
      detail: error instanceof Error ? error.message : String(error),
    });
    finish();
  });
}

/** Warns without failing — used for environment facts that are informational. */
export function note(message: string): void {
  process.stdout.write(`  ${COLOR.yellow}!${COLOR.reset} ${message}\n`);
}
