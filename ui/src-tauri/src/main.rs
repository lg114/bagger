// Never show a console window on Windows — even in debug builds.
#![windows_subsystem = "windows"]

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

struct BackendProcess(Mutex<Option<Child>>);

const BACKEND_PORT: u16 = 8723;

fn spawn_backend() -> Option<Child> {
    // Strategy 1: bagger CLI (if installed via pip)
    let mut cmd = Command::new("bagger");
    cmd.args(["serve", "--port", &BACKEND_PORT.to_string(), "--no-open"])
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    suppress_console(&mut cmd);
    let result = cmd.spawn();

    let child = match result {
        Ok(c) => {
            println!("Bagger backend started via CLI (PID: {})", c.id());
            Some(c)
        }
        Err(_) => {
            // Strategy 2: python -m bagger (needs __main__.py and pip install)
            let mut cmd = Command::new("python");
            cmd.args(["-m", "bagger", "serve", "--port", &BACKEND_PORT.to_string(), "--no-open"])
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            suppress_console(&mut cmd);
            let result = cmd.spawn();

            match result {
                Ok(c) => {
                    println!("Bagger backend started via python -m (PID: {})", c.id());
                    Some(c)
                }
                Err(e) => {
                    eprintln!(
                        "Failed to start Bagger API server: {}\n\
                         Make sure bagger is installed in this Python environment:\n\
                           cd path/to/bagger && pip install -e \".[web]\"",
                        e
                    );
                    None
                }
            }
        }
    };

    // Do NOT block the main thread waiting for the backend — that would
    // freeze the window as "Not Responding". The frontend shows loading
    // skeletons until the API becomes available.
    child
}

/// Background health monitor. Runs on a separate thread; logs when the
/// backend becomes available (or warns if it never does).
fn monitor_backend_health() {
    let url = format!("http://127.0.0.1:{}/api/health", BACKEND_PORT);
    std::thread::spawn(move || {
        for i in 0..30 {
            std::thread::sleep(Duration::from_millis(200));
            match ureq::get(&url).call() {
                Ok(_) => {
                    println!("Bagger backend is healthy (attempt {})", i + 1);
                    return;
                }
                Err(_) => continue,
            }
        }
        eprintln!(
            "Warning: Bagger backend did not become healthy within 6 seconds. \
             Make sure `pip install -e \".[web]\"` has been run."
        );
    });
}

/// Prevent a spawned Command from opening a console window on Windows.
#[cfg(windows)]
fn suppress_console(cmd: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(windows))]
fn suppress_console(_cmd: &mut Command) {}

// ── Single-instance guard (Windows: named mutex; other: port check) ──

/// Try to acquire the global application mutex (Windows) or lock file (other).
/// Returns `true` if this is the only instance.
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
        fn CloseHandle(handle: isize) -> i32;
    }

    const ERROR_ALREADY_EXISTS: u32 = 183;

    let wide: Vec<u16> = OsStr::new("Global\\BaggerAppSingleInstance")
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 1, wide.as_ptr());
        if handle == 0 {
            // Mutex creation itself failed — allow startup (shouldn't happen)
            return true;
        }
        if GetLastError() == ERROR_ALREADY_EXISTS {
            CloseHandle(handle);
            return false;
        }
        // We own the mutex. The raw handle (isize) stays alive until the
        // process exits; the OS will release the kernel mutex automatically.
        let _ = handle; // suppress unused-variable warning
        true
    }
}

#[cfg(not(windows))]
fn acquire_single_instance_lock() -> bool {
    use std::net::TcpStream;
    // Fallback: check if the backend port is already occupied.
    let addr = format!("127.0.0.1:{}", BACKEND_PORT)
        .parse()
        .expect("invalid backend address");
    // Give the old instance a moment to shut down during dev restarts.
    for _ in 0..10 {
        match TcpStream::connect_timeout(&addr, Duration::from_millis(200)) {
            Ok(_) => std::thread::sleep(Duration::from_millis(500)),
            Err(_) => return true,
        }
    }
    false
}

fn main() {
    // Prevent duplicate windows: use a named mutex so only one instance runs.
    if !acquire_single_instance_lock() {
        eprintln!("Another Bagger instance is already running. Exiting.");
        std::process::exit(1);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .setup(|app| {
            // Spawn the Python backend (do NOT block — window must stay responsive).
            let child = spawn_backend();
            app.manage(BackendProcess(Mutex::new(child)));
            monitor_backend_health();

            // Build tray menu
            let show = MenuItemBuilder::with_id("show", "Show Bagger").build(app)?;
            let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
            let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;
            let menu = MenuBuilder::new(app)
                .item(&show)
                .item(&separator)
                .item(&quit)
                .build()?;

            // Build tray icon
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
                        // Kill the Python backend
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
                // In dev mode, allow real close to avoid duplicate windows.
                // In release mode, hide to tray.
                if cfg!(debug_assertions) {
                    // Let the window close normally; RunEvent::Exit will kill backend.
                } else {
                    window.hide().ok();
                    api.prevent_close();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri app")
        .run(|_app, event| {
            // Clean up backend process on exit
            if let RunEvent::Exit = event {
                if let Some(backend) = _app.try_state::<BackendProcess>() {
                    if let Some(mut child) = backend.0.lock().unwrap().take() {
                        child.kill().ok();
                    }
                }
            }
        });
}
