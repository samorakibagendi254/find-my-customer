#!/usr/bin/env node

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

const SKILL_NAME = "find-first-customers";

function usage() {
  console.log(`
Find First Customers skill installer

Usage:
  npx codex-find-first-customers-skill
  node scripts/install.js --skills-dir ~/.codex/skills

Options:
  --skills-dir PATH  Install into a custom Codex skills directory
  --dry-run          Print the destination without changing files
  --help             Show this help
`);
}

function expandHome(value) {
  if (!value) return value;
  if (value === "~") return os.homedir();
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(os.homedir(), value.slice(2));
  }
  return value;
}

function parseArgs(argv) {
  const options = { dryRun: false, help: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") {
      options.help = true;
    } else if (argument === "--dry-run") {
      options.dryRun = true;
    } else if (argument === "--skills-dir") {
      const value = argv[index + 1];
      if (!value) throw new Error("--skills-dir requires a value");
      options.skillsDir = expandHome(value);
      index += 1;
    } else {
      throw new Error(`Unknown option: ${argument}`);
    }
  }
  return options;
}

function defaultSkillsDir() {
  const codexHome = process.env.CODEX_HOME || path.join(os.homedir(), ".codex");
  return path.join(codexHome, "skills");
}

function shouldCopy(name) {
  return name !== "__pycache__" && !name.endsWith(".pyc") && !name.endsWith(".pyo");
}

function copyDirectory(source, destination) {
  fs.mkdirSync(destination, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    if (!shouldCopy(entry.name)) continue;
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);
    if (entry.isDirectory()) {
      copyDirectory(sourcePath, destinationPath);
    } else if (entry.isFile()) {
      fs.copyFileSync(sourcePath, destinationPath);
    }
  }
}

function samePath(left, right) {
  const normalize = (value) => path.resolve(value).replace(/[\\/]+$/, "").toLowerCase();
  return normalize(left) === normalize(right);
}

function install(options) {
  const source = path.resolve(__dirname, "..", SKILL_NAME);
  const skillsDir = path.resolve(options.skillsDir || defaultSkillsDir());
  const destination = path.join(skillsDir, SKILL_NAME);

  if (!fs.existsSync(path.join(source, "SKILL.md"))) {
    throw new Error(`Cannot find a complete bundled skill at ${source}`);
  }
  if (samePath(source, destination)) {
    throw new Error("The repository skill is already at the installation destination; refusing to replace its source files");
  }
  if (options.dryRun) {
    console.log(`Would install ${SKILL_NAME} to ${destination}`);
    return destination;
  }

  fs.mkdirSync(skillsDir, { recursive: true });
  const token = `${process.pid}-${Date.now()}`;
  const staging = path.join(skillsDir, `.${SKILL_NAME}.install-${token}`);
  const backup = path.join(skillsDir, `.${SKILL_NAME}.backup-${token}`);
  let movedExisting = false;

  try {
    copyDirectory(source, staging);
    if (!fs.existsSync(path.join(staging, "SKILL.md"))) {
      throw new Error("Staged skill is incomplete");
    }
    if (fs.existsSync(destination)) {
      fs.renameSync(destination, backup);
      movedExisting = true;
    }
    fs.renameSync(staging, destination);
    if (movedExisting) fs.rmSync(backup, { recursive: true, force: true });
  } catch (error) {
    if (fs.existsSync(staging)) fs.rmSync(staging, { recursive: true, force: true });
    if (movedExisting && !fs.existsSync(destination) && fs.existsSync(backup)) {
      fs.renameSync(backup, destination);
    }
    throw error;
  }

  console.log(`Installed ${SKILL_NAME}.`);
  console.log(`Location: ${destination}`);
  console.log("Restart Codex, then invoke $find-first-customers.");
  return destination;
}

function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }
  install(options);
}

try {
  main();
} catch (error) {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
}

