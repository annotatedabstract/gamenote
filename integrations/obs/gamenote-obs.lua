-- gamenote-obs.lua
-- OBS bridge for gamenote's optional OBS features. Writes a single JSON sidecar,
-- gamenote-obs.json, into the chosen folder, holding:
--   game          the active scene name (best-effort "game" for context-from-file)
--   session_start recording start time            YYYY-MM-DD_HH-MM-SS
--   file_start    start of the CURRENT file segment (updated on each split)
--   file_path     the current recording file
--   recording     true while recording, false once it stops
--
-- gamenote reads from it via the profile's "Read OBS recording info from a
-- file" option (point its "OBS file" at <folder>\gamenote-obs.json):
--   * session_start -> the `## Recording session:` header value
--                      (with "Write session headers" on)
--   * file_start    -> the {clip} prefix token, i.e. how far into the current
--                      recording the note is
--   * file_path     -> the `### Recording file:` sub-header naming the file
--                      each {clip} offset refers to (with session headers on)
--   * game          -> the {context} value, per profile ("Also read {context}
--                      (the game) from this file") or globally (Settings >
--                      Context > "Read context from a file" pointed here)
--
-- file_start is re-stamped on OBS's "file_changed" signal, so the {clip} offset
-- stays correct even when OBS automatic file splitting starts a new file
-- mid-session. Requires OBS 28+ (the file_changed signal); on older OBS the
-- offset simply does not reset across splits.

obs = obslua

-- Set from the OBS Scripts UI (Tools > Scripts).
local sidecar_dir = [[N:\Recordings]]

-- Current recording state, serialized to gamenote-obs.json on every change.
local state = {
  game = "",
  session_start = "",
  file_start = "",
  file_path = "",
  recording = false,
}

-- Held for the duration of a recording so the file_changed signal stays
-- connected and can be cleanly disconnected (and the ref released) on stop.
local record_output = nil

local function log(msg) obs.script_log(obs.LOG_INFO, "[gamenote-obs] " .. msg) end

local function now_stamp() return os.date("%Y-%m-%d_%H-%M-%S") end

local function join_path(dir, name)
  dir = dir:gsub("[\\/]+$", "")
  return dir .. "\\" .. name
end

-- The active scene name, a best-effort "game" value.
local function current_scene_name()
  local scene = obs.obs_frontend_get_current_scene()
  if scene == nil then return "" end
  local name = obs.obs_source_get_name(scene)
  obs.obs_source_release(scene)
  return name or ""
end

-- The current recording output's file path (best effort; may be empty briefly).
local function current_record_path()
  local output = obs.obs_frontend_get_recording_output()
  if output == nil then return "" end
  local settings = obs.obs_output_get_settings(output)
  local path = obs.obs_data_get_string(settings, "path")
  obs.obs_data_release(settings)
  obs.obs_output_release(output)
  return path or ""
end

-- Serialize `state` to gamenote-obs.json. obs_data handles JSON escaping, so
-- Windows backslash paths are written as valid JSON.
local function write_sidecar()
  if sidecar_dir == "" then return end
  local d = obs.obs_data_create()
  obs.obs_data_set_string(d, "game", state.game)
  obs.obs_data_set_string(d, "session_start", state.session_start)
  obs.obs_data_set_string(d, "file_start", state.file_start)
  obs.obs_data_set_string(d, "file_path", state.file_path)
  obs.obs_data_set_bool(d, "recording", state.recording)
  local json = obs.obs_data_get_json(d)
  obs.obs_data_release(d)

  local path = join_path(sidecar_dir, "gamenote-obs.json")
  local f, err = io.open(path, "w")
  if not f then
    log("ERROR writing " .. path .. ": " .. tostring(err))
    return
  end
  f:write(json)
  f:close()
end

-- OBS fires this when automatic file splitting rolls over to a new file.
local function on_file_changed(cd)
  local next_file = obs.calldata_string(cd, "next_file")
  state.file_start = now_stamp()
  if next_file ~= nil and next_file ~= "" then
    state.file_path = next_file
  end
  write_sidecar()
  log("File split; file_start reset to " .. state.file_start)
end

local function on_recording_started()
  local stamp = now_stamp()
  state.game = current_scene_name()
  state.session_start = stamp
  state.file_start = stamp
  state.file_path = current_record_path()
  state.recording = true
  write_sidecar()
  log("Recording started; wrote gamenote-obs.json")

  -- Connect file_changed so file_start re-stamps on each split (OBS 28+).
  if record_output == nil then
    record_output = obs.obs_frontend_get_recording_output()
    if record_output ~= nil then
      local sh = obs.obs_output_get_signal_handler(record_output)
      obs.signal_handler_connect(sh, "file_changed", on_file_changed)
    end
  end
end

local function on_recording_stopped()
  state.recording = false
  write_sidecar()
  if record_output ~= nil then
    local sh = obs.obs_output_get_signal_handler(record_output)
    obs.signal_handler_disconnect(sh, "file_changed", on_file_changed)
    obs.obs_output_release(record_output)
    record_output = nil
  end
  log("Recording stopped")
end

function on_event(event)
  if event == obs.OBS_FRONTEND_EVENT_RECORDING_STARTED then
    on_recording_started()
  elseif event == obs.OBS_FRONTEND_EVENT_RECORDING_STOPPED then
    on_recording_stopped()
  end
end

-- ===== OBS Script plumbing =====
function script_description()
  return [[Writes gamenote-obs.json (game, session_start, file_start, file_path,
recording) into the chosen folder while recording, for gamenote's optional
session-header, {clip} recording-position, and game-as-context features.
file_start updates on each automatic file split (OBS 28+). Point the gamenote
profile's "OBS file" at <folder>\gamenote-obs.json.]]
end

function script_defaults(s)
  obs.obs_data_set_default_string(s, "sidecar_dir", [[N:\Recordings]])
end

function script_properties()
  local p = obs.obs_properties_create()
  obs.obs_properties_add_path(p, "sidecar_dir", "Folder for gamenote-obs.json",
                              obs.OBS_PATH_DIRECTORY, nil, nil)
  return p
end

function script_update(s)
  sidecar_dir = obs.obs_data_get_string(s, "sidecar_dir")
  if sidecar_dir == "" then sidecar_dir = [[N:\Recordings]] end
end

function script_load(s)
  obs.obs_frontend_add_event_callback(on_event)
  log("Loaded. Will write gamenote-obs.json on recording start.")
end

function script_unload()
  -- Clean up if the script is unloaded mid-recording.
  if record_output ~= nil then
    local sh = obs.obs_output_get_signal_handler(record_output)
    obs.signal_handler_disconnect(sh, "file_changed", on_file_changed)
    obs.obs_output_release(record_output)
    record_output = nil
  end
end
