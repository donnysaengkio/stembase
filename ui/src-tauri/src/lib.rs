//! Stembase desktop shell: the window, plus the audio engine (a Python process) running beside it.
//!
//! The engine prints "STEMBASE_PORT=<port>" when it is listening; the interface asks for that port and a secret token
//! with the `engine` command, then talks to the engine's local web API. The engine stops when the app closes: it is
//! killed on exit, and it also quits by itself when this process is gone (it watches STEMBASE_PARENT_PID).

use std::io::{BufRead, BufReader, Read};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

#[derive(Default)]
struct Engine {
    port: Option<u16>,
    error: Option<String>,
    child: Option<Child>,
}

struct EngineState {
    token: String,
    inner: Mutex<Engine>,
}

#[derive(serde::Serialize)]
struct EngineInfo {
    port: Option<u16>,
    token: String,
    error: Option<String>,
}

/// The interface polls this until the engine's port is known (or it failed to start).
#[tauri::command]
fn engine(state: tauri::State<EngineState>) -> EngineInfo {
    let e = state.inner.lock().unwrap();
    EngineInfo { port: e.port, token: state.token.clone(), error: e.error.clone() }
}

/// How to start the engine: STEMBASE_ENGINE overrides; release builds run the bundled engine; debug builds run
/// `python server.py` from the project folder.
fn engine_command(app: &tauri::AppHandle) -> Result<Command, String> {
    if let Ok(exe) = std::env::var("STEMBASE_ENGINE") {
        return Ok(Command::new(exe));
    }
    if cfg!(debug_assertions) {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..");
        let python = std::env::var("STEMBASE_PYTHON").unwrap_or_else(|_| "python".into());
        let mut c = Command::new(python);
        c.arg(root.join("server.py")).current_dir(root);
        return Ok(c);
    }
    let dir = app.path().resource_dir().map_err(|e| e.to_string())?.join("engine");
    let exe = dir.join(if cfg!(windows) { "stembase-engine.exe" } else { "stembase-engine" });
    if !exe.exists() {
        return Err(format!("The audio engine is missing: {}", exe.display()));
    }
    let mut c = Command::new(exe);
    c.current_dir(dir);
    Ok(c)
}

fn start_engine(app: tauri::AppHandle) {
    let state = app.state::<EngineState>();
    let fail = |msg: String| state.inner.lock().unwrap().error = Some(msg);
    let mut cmd = match engine_command(&app) {
        Ok(c) => c,
        Err(e) => return fail(e),
    };
    cmd.env("STEMBASE_TOKEN", &state.token)
        .env("STEMBASE_PARENT_PID", std::process::id().to_string())
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(if cfg!(debug_assertions) { Stdio::inherit() } else { Stdio::null() });
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console window for the engine
    }
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return fail(format!("Could not start the audio engine: {e}")),
    };
    let stdout = child.stdout.take().unwrap();
    state.inner.lock().unwrap().child = Some(child);

    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    loop {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) | Err(_) => return fail("The audio engine stopped while starting.".into()),
            Ok(_) => {
                if let Some(p) = line.trim().strip_prefix("STEMBASE_PORT=") {
                    state.inner.lock().unwrap().port = p.parse().ok();
                    break;
                }
            }
        }
    }
    // Keep reading whatever else it prints, so its output pipe never fills up and blocks it.
    std::thread::spawn(move || {
        let mut sink = [0u8; 4096];
        while matches!(reader.read(&mut sink), Ok(n) if n > 0) {}
    });
}

/// Quit Stembase (menu or Ctrl+Q): closes the window; the engine is stopped on exit.
#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_opener::init())
        .manage(EngineState { token: uuid::Uuid::new_v4().simple().to_string(), inner: Mutex::new(Engine::default()) })
        .invoke_handler(tauri::generate_handler![engine, quit])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || start_engine(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Stembase")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<EngineState>().inner.lock().unwrap().child.take() {
                    let _ = child.kill();
                }
            }
        });
}
