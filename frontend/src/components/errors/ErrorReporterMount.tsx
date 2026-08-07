"use client";
import { useEffect } from "react";
import { installGlobalErrorReporting } from "@/lib/error-reporter";

/** Mounted once in the root layout — installs window-level handlers so
 *  uncaught exceptions and unhandled rejections reach /admin/error-logs.
 *  Renders nothing; install is idempotent across hot reloads. */
export function ErrorReporterMount() {
  useEffect(() => { installGlobalErrorReporting(); }, []);
  return null;
}
