-- gamenote-session.lua
-- Minimal OBS script for gamenote's optional "session header from file" feature.
--
-- On RECORDING_STARTED it writes a single file:
--   <Session folder>\.current_session   ->  YYYY-MM-DD_HH-MM-SS  (recording start time)
--
-- Point a gamenote profile's "Session file" at that same path and tick
-- "Read session value from a file" so notes get a `## Recording session:` header
-- stamped with the recording's start time. That is all this script does: no BAT,
-- no .current_game, no renaming. (The full workflow script is separate.)

obs = obslua

-- Set from the OBS Scripts UI (Tools > Scripts).
local session_dir = [[N:\Recordings]]

local function log(msg) obs.script_log(obs.LOG_INFO, "[gamenote-session] " .. msg) end

local function join_path(dir, name)
  dir = dir:gsub("[\\/]+$", "")
  return dir .. "\\" .. name
end

local function write_current_session()
  if session_dir == "" then return end
  local path = join_path(session_dir, ".current_session")
  local f, err = io.open(path, "w")
  if not f then
    log("ERROR writing " .. path .. ": " .. tostring(err))
    return
  end
  f:write(os.date("%Y-%m-%d_%H-%M-%S"))
  f:close()
  log("Wrote " .. path)
end

function on_event(event)
  if event == obs.OBS_FRONTEND_EVENT_RECORDING_STARTED then
    write_current_session()
  end
end

-- ===== OBS Script plumbing =====
function script_description()
  return [[Writes .current_session (recording start time, YYYY-MM-DD_HH-MM-SS) into
the chosen folder when recording starts, for gamenote's optional session-header
feature. Point a gamenote profile's "Session file" at <folder>\.current_session.]]
end

function script_defaults(s)
  obs.obs_data_set_default_string(s, "session_dir", [[N:\Recordings]])
end

function script_properties()
  local p = obs.obs_properties_create()
  obs.obs_properties_add_path(p, "session_dir", "Session folder (.current_session)",
                              obs.OBS_PATH_DIRECTORY, nil, nil)
  return p
end

function script_update(s)
  session_dir = obs.obs_data_get_string(s, "session_dir")
  if session_dir == "" then session_dir = [[N:\Recordings]] end
end

function script_load(s)
  obs.obs_frontend_add_event_callback(on_event)
  log("Loaded. Will write .current_session on recording start.")
end
