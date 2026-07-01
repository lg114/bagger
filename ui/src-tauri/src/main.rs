// Never show a console window on Windows — even in debug builds.
#![windows_subsystem = "windows"]

use std::fs::File;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;
#[cfg(not(windows))]
use std::net::TcpStream;
use tauri::{
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent,
};

// ── Platform constants for sidecar naming ──

#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
const TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
const TARGET_TRIPLE: &str = "aarch64-apple-darwin";
#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
const TARGET_TRIPLE: &str = "x86_64-apple-darwin";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
const TARGET_TRIPLE: &str = "x86_64-unknown-linux-gnu";

#[cfg(target_os = "windows")]
const EXE_EXT: &str = ".exe";
#[cfg(not(target_os = "windows"))]
const EXE_EXT: &str = "";

const BACKEND_PORT: u16 = 8723;

// ── Backend mode: Sidecar (production) vs HostPython (development) ──

#[derive(Clone)]
enum BackendMode {
    Sidecar,      // Bundled exe in resource dir
    HostPython,   // Host Python + pip install (dev mode)
}

/// Detect mode by checking if a real sidecar binary (>1MB) exists.
/// A placeholder file (a few bytes) satisfies Tauri's build check but
/// won't trigger Sidecar mode — dev mode remains HostPython.
fn detect_backend_mode(app: &tauri::AppHandle) -> BackendMode {
    if let Ok(dir) = app.path().resource_dir() {
        let name = format!("bagger-server-{}{}", TARGET_TRIPLE, EXE_EXT);
        let path = dir.join("binaries").join(&name);
        // Real PyInstaller bundles are 30-40MB; placeholders are tiny.
        if path.exists() && path.metadata().map(|m| m.len() > 1_000_000).unwrap_or(false) {
            println!("Detected sidecar binary ({} bytes) - production mode",
                     path.metadata().map(|m| m.len()).unwrap_or(0));
            return BackendMode::Sidecar;
        }
    }
    println!("No real sidecar binary - development mode (requires pip install)");
    BackendMode::HostPython
}

struct BackendProcess(Mutex<Option<Child>>);

// ── Backend log file ──

/// Open ~/.bagger/backend.log for appending. In dev mode, backend stderr
/// is redirected here so startup errors are visible. In production, stderr
/// goes to null (sidecar is self-contained).
fn open_backend_log() -> Option<File> {
    let log_path = home_dir().join(".bagger").join("backend.log");
    if let Some(parent) = log_path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    File::options()
        .append(true)
        .create(true)
        .open(&log_path)
        .ok()
        .map(|f| {
            println!("Backend stderr → {}", log_path.display());
            f
        })
}

fn home_dir() -> PathBuf {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .or_else(|_| std::env::var("HOMEDRIVE").map(|d| {
            let path = std::env::var("HOMEPATH").unwrap_or_default();
            format!("{}{}", d, path)
        }))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

// ── Backend spawning ──

fn spawn_backend(app: &tauri::AppHandle, mode: &BackendMode) -> Option<Child> {
    let port = BACKEND_PORT.to_string();

    match mode {
        BackendMode::Sidecar => {
            // Resolve sidecar path from resource directory
            let resource_dir = app.path().resource_dir()
                .expect("resource directory not available");
            let sidecar_name = format!("bagger-server-{}{}", TARGET_TRIPLE, EXE_EXT);
            let sidecar_path = resource_dir.join("binaries").join(&sidecar_name);

            let mut cmd = Command::new(&sidecar_path);
            cmd.args(["serve", "--port", &port, "--no-open"])
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            suppress_console(&mut cmd);

            match cmd.spawn() {
                Ok(c) => {
                    println!("Bagger backend started via sidecar (PID: {})", c.id());
                    Some(c)
                }
                Err(e) => {
                    eprintln!("Sidecar spawn failed: {} - binary may be corrupted.", e);
                    None
                }
            }
        }
        BackendMode::HostPython => {
            // In dev mode, redirect stderr to ~/.bagger/backend.log
            // so startup errors are visible instead of silently swallowed.
            let stderr_dest: Stdio = open_backend_log()
                .map(Stdio::from)
                .unwrap_or(Stdio::null());

            // --reload makes uvicorn spawn a child subprocess for hot-reloading.
            // On Windows, that child creates a visible console window even though
            // the parent has CREATE_NO_WINDOW — resulting in multiple black popups.
            // Only use --reload on macOS/Linux where this isn't an issue.
            #[cfg(windows)]
            let reload_args: &[&str] = &[];
            #[cfg(not(windows))]
            let reload_args: &[&str] = &["--reload"];

            // Strategy 1: bagger CLI
            let mut cmd = Command::new("bagger");
            cmd.args(["serve", "--port", &port, "--no-open"])
                .args(reload_args)
                .stdout(Stdio::null())
                .stderr(stderr_dest);
            suppress_console(&mut cmd);

            match cmd.spawn() {
                Ok(c) => {
                    println!("Bagger backend started via CLI (dev, PID: {})", c.id());
                    Some(c)
                }
                Err(_) => {
                    // Strategy 2: python -m bagger (fallback for pip install -e)
                    // Re-open log for second attempt
                    let stderr_dest2: Stdio = open_backend_log()
                        .map(Stdio::from)
                        .unwrap_or(Stdio::null());

                    let mut cmd = Command::new("python");
                    cmd.args(["-m", "bagger", "serve", "--port", &port, "--no-open"])
                        .args(reload_args)
                        .stdout(Stdio::null())
                        .stderr(stderr_dest2);
                    suppress_console(&mut cmd);

                    match cmd.spawn() {
                        Ok(c) => {
                            println!("Bagger backend started via python -m (dev, PID: {})", c.id());
                            Some(c)
                        }
                        Err(e) => {
                            // Write the error to the log file too
                            if let Some(mut log) = open_backend_log() {
                                let msg = format!(
                                    "Development mode failed: {}\nInstall bagger: pip install -e \".[web]\"\n",
                                    e
                                );
                                log.write_all(msg.as_bytes()).ok();
                            }
                            eprintln!(
                                "Development mode failed: {}\n\
                                 Install bagger: pip install -e \".[web]\"\n\
                                 Check ~/.bagger/backend.log for details.",
                                e
                            );
                            None
                        }
                    }
                }
            }
        }
    }
}

// ── Health monitor with auto-restart ──
//
// Polls the backend health endpoint for up to 6 seconds.
// If the backend doesn't respond, logs a warning.
// Also starts a background watcher that detects backend crashes
// during runtime and attempts to restart it.

fn monitor_backend_health(app: &tauri::AppHandle, mode: &BackendMode) {
    let url = format!("http://127.0.0.1:{}/api/health", BACKEND_PORT);
    let hint = match mode {
        BackendMode::Sidecar => "The bundled binary may be corrupted. Check ~/.bagger/backend.log.",
        BackendMode::HostPython => "Make sure `pip install -e \".[web]\"` has been run. Check ~/.bagger/backend.log.",
    };

    // Initial health check: poll for up to 6 seconds
    let healthy = std::thread::scope(|s| {
        let handle = s.spawn(|| {
            for i in 0..30 {
                std::thread::sleep(Duration::from_millis(200));
                if ureq::get(&url).call().is_ok() {
                    println!("Bagger backend is healthy (attempt {})", i + 1);
                    return true;
                }
            }
            eprintln!("Warning: backend not healthy within 6s. {}", hint);
            if let Some(mut log) = open_backend_log() {
                let msg = format!("Backend health check failed after 6s. {}\n", hint);
                log.write_all(msg.as_bytes()).ok();
            }
            false
        });
        handle.join().unwrap()
    });

    // Start background crash watcher
    if healthy {
        start_backend_watcher(app, mode);
    }
}

/// Background thread that checks backend health every 30s.
/// If the backend crashes, attempts to restart it (up to 3 times).
fn start_backend_watcher(app: &tauri::AppHandle, mode: &BackendMode) {
    let url = format!("http://127.0.0.1:{}/api/health", BACKEND_PORT);
    let app_handle = app.clone();
    let mode_clone = mode.clone(); // BackendMode needs Clone

    std::thread::spawn(move || {
        let mut restart_attempts = 0;
        loop {
            std::thread::sleep(Duration::from_secs(30));
            if ureq::get(&url).call().is_err() {
                println!("Backend crashed! Attempting restart (attempt {})", restart_attempts + 1);
                if let Some(mut log) = open_backend_log() {
                    let msg = format!("Backend crash detected. Restart attempt {}.\n", restart_attempts + 1);
                    log.write_all(msg.as_bytes()).ok();
                }

                // Kill the old process if it's still lingering
                if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                    if let Some(mut child) = backend.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait(); // Ensure process is fully dead
                    }
                }

                // Restart
                let new_child = spawn_backend(&app_handle, &mode_clone);
                if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                    *backend.0.lock().unwrap() = new_child;
                }

                // Wait for backend to come back
                let mut recovered = false;
                for _i in 0..30 {
                    std::thread::sleep(Duration::from_millis(200));
                    if ureq::get(&url).call().is_ok() {
                        println!("Backend recovered after restart (attempt {})", restart_attempts + 1);
                        recovered = true;
                        break;
                    }
                }

                if recovered {
                    restart_attempts = 0; // Reset on successful recovery
                } else {
                    restart_attempts += 1;
                    if restart_attempts >= 3 {
                        eprintln!("Backend failed to restart 3 times. Giving up.");
                        if let Some(mut log) = open_backend_log() {
                            log.write_all(b"Backend restart failed 3 times. Giving up.\n").ok();
                        }
                        return; // Stop watching
                    }
                }
            } else {
                restart_attempts = 0; // Reset on healthy check
            }
        }
    });
}

// ── Console suppression (Windows only) ──

#[cfg(windows)]
fn suppress_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn suppress_console(_cmd: &mut Command) {}

// ── Single-instance guard ──
//
// Strategy: Try to create a named mutex. If it already exists:
// 1. Check if the backend on port BACKEND_PORT is alive.
// 2. If alive → the previous instance is genuinely running → exit.
// 3. If dead → the previous instance crashed, take over the mutex.
//
// This prevents a zombie Tauri window (alive but backend dead) from
// blocking new launches.

/// Check if the backend health endpoint is reachable.
fn is_backend_alive() -> bool {
    let url = format!("http://127.0.0.1:{}/api/health", BACKEND_PORT);
    ureq::get(&url).call().is_ok()
}

#[cfg(windows)]
fn acquire_single_instance_lock() -> bool {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    extern "system" {
        fn CreateMutexW(
            lpMutexAttributes: *const std::ffi::c_void,
            bInitialOwner: i32,
            lpName: *const u16,
        ) -> isize;
        fn GetLastError() -> u32;
    }

    const ERROR_ALREADY_EXISTS: u32 = 183;

    let wide: Vec<u16> = OsStr::new("Global\\BaggerAppSingleInstance")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 1, wide.as_ptr());
        if handle == 0 {
            // Failed to create mutex — proceed anyway
            return true;
        }
        if GetLastError() == ERROR_ALREADY_EXISTS {
            // Mutex held by another process — is it actually alive?
            if is_backend_alive() {
                eprintln!("Another Bagger instance is running (backend healthy). Exiting.");
                return false;
            }
            // Previous instance crashed (backend dead) — take over.
            eprintln!("Previous Bagger instance crashed (backend dead). Taking over.");
        }
        true
    }
}

#[cfg(not(windows))]
fn acquire_single_instance_lock() -> bool {
    // On non-Windows, check if backend is alive on the port
    if is_backend_alive() {
        eprintln!("Another Bagger instance is running (backend healthy). Exiting.");
        return false;
    }
    true
}

fn main() {
    // BAGGER_SKIP_BACKEND=1 lets you run the backend separately
    // (e.g. `bagger serve --reload`) without Tauri also spawning one.
    // When using this dev workflow, also skip the single-instance lock —
    // the backend alive on port 8723 would otherwise fool the "smart" lock
    // into thinking another Bagger instance is running.
    let skip_backend = std::env::var("BAGGER_SKIP_BACKEND")
        .map(|v| v == "1" || v == "true")
        .unwrap_or(false);

    if !skip_backend && !acquire_single_instance_lock() {
        eprintln!("Another Bagger instance is already running. Exiting.");
        std::process::exit(1);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            let skip_backend = std::env::var("BAGGER_SKIP_BACKEND")
                .map(|v| v == "1" || v == "true")
                .unwrap_or(false);

            if skip_backend {
                println!("BAGGER_SKIP_BACKEND set — skipping backend spawn.");
                app.manage(BackendProcess(Mutex::new(None)));
            } else {
                let mode = detect_backend_mode(app.handle());
                let child = spawn_backend(app.handle(), &mode);
                app.manage(BackendProcess(Mutex::new(child)));
                monitor_backend_health(app.handle(), &mode);
            }

            let show = MenuItemBuilder::with_id("show", "Show Bagger").build(app)?;
            let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit Bagger").build(app)?;
            let menu = MenuBuilder::new(app)
                .item(&show)
                .item(&separator)
                .item(&quit)
                .build()?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(move |app_handle, event| match event.id().as_ref() {
                    "show" => {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            window.show().ok();
                            window.set_focus().ok();
                        }
                    }
                    "quit" => {
                        if let Some(backend) = app_handle.try_state::<BackendProcess>() {
                            if let Some(mut child) = backend.0.lock().unwrap().take() {
                                child.kill().ok();
                            }
                        }
                        app_handle.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            window.show().ok();
                            window.set_focus().ok();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if cfg!(debug_assertions) {
                    // Dev: let window close normally
                } else {
                    // Release: hide to tray
                    window.hide().ok();
                    api.prevent_close();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app")
        .run(|_app, event| {
            if let RunEvent::Exit = event {
                if let Some(backend) = _app.try_state::<BackendProcess>() {
                    if let Some(mut child) = backend.0.lock().unwrap().take() {
                        child.kill().ok();
                    }
                }
            }
        });
}
