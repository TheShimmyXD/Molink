from __future__ import annotations

from modules.mod_03_console.logic._03_logic_console import (
    NO_TARGET,
    ConsoleLogic,
    ConsoleState,
    OutputDecoder,
    Tone,
)
from modules.mod_03_console.logic._03_logic_shell import Place

PEER = ("sobremesa", "192.0.2.20")
OTHER = ("taller", "192.0.2.30")


def test_targets_choose_the_first_and_keep_the_choice():
    logic = ConsoleLogic()
    assert logic.state == ConsoleState.NO_TARGET and logic.view()["status"] is NO_TARGET
    logic.set_targets([PEER, OTHER])
    assert logic.state == ConsoleState.READY and logic.target == "sobremesa"
    assert logic.choose("taller") and not logic.choose("nadie")
    logic.set_targets([OTHER, PEER])
    assert logic.view()["address"] == "192.0.2.30"
    logic.set_targets([PEER])
    assert logic.target == "sobremesa"
    logic.set_targets([])
    assert logic.state == ConsoleState.NO_TARGET and logic.target == ""


def test_start_run_checks_target_command_and_busy():
    logic = ConsoleLogic()
    assert not logic.start_run("hostname", 0.0)["ok"]
    logic.set_targets([PEER])
    assert logic.start_run("   ", 0.0)["message"] == "Escribe un comando."
    payload = logic.start_run("  hostname ", 1.0)
    assert payload["ok"] and not payload["asking"] and payload["stdin"] == b""
    assert (payload["target"], payload["command"]) == ("sobremesa", "hostname")
    assert payload["script"].startswith("cd\n") and payload["script"].endswith("\nhostname")
    assert logic.view()["running"] and not logic.start_run("ls", 1.0)["ok"]
    assert not logic.choose("sobremesa")


def test_outcomes_by_exit_status_and_error():
    logic = ConsoleLogic()
    logic.set_targets([PEER])
    cases = [
        ((True, 0), "Terminó con código 0 en 0,4 s.", Tone.OK),
        ((True, 2), "Terminó con código 2 en 0,4 s.", Tone.WARNING),
        ((True, None), "Terminó sin código de salida en 0,4 s.", Tone.WARNING),
    ]
    for (ok, status), text, tone in cases:
        logic.start_run("x", 10.0)
        logic.run_finished(ok, status, 10.42)
        assert (logic.outcome.text, logic.outcome.tone) == (text, tone)
        assert logic.state == ConsoleState.READY
    logic.start_run("x", 0.0)
    logic.run_finished(False, None, 1.0, "Se perdió la conexión con sobremesa.", "Revisa la red.")
    assert logic.outcome.tone == Tone.ERROR and logic.outcome.hint == "Revisa la red."


def test_cancel_and_target_lost_while_running():
    logic = ConsoleLogic()
    logic.set_targets([PEER, OTHER])
    logic.start_run("sleep 30", 0.0)
    logic.set_targets([OTHER])
    assert logic.is_running and logic.target == "sobremesa"
    assert logic.cancel(2.06)
    assert logic.outcome.text == "Cancelado a los 2,1 s." and logic.target == "taller"
    logic.run_finished(True, 143, 3.0)  # llega despues de cancelar: no cambia nada
    assert logic.outcome.text.startswith("Cancelado") and not logic.cancel(4.0)


def test_decoder_joins_split_letters_and_crlf():
    decoder = OutputDecoder()
    data = "ñandú\r\nlisto".encode()
    text = decoder.feed("stdout", data[:1]) + decoder.feed("stdout", data[1:4])
    text += decoder.feed("stderr", b"\xc3") + decoder.feed("stdout", data[4:])
    assert text == "ñandú\nlisto"
    assert decoder.flush() == "�"
    assert decoder.feed("stderr", "é".encode()) == "é"


def test_sudo_asks_for_password_and_cancel_runs_nothing():
    logic = ConsoleLogic()
    logic.set_targets([PEER])
    assert logic.start_run("sudo apt update", 0.0) == {
        "ok": True,
        "asking": True,
        "command": "sudo apt update",
    }
    assert logic.view()["asking"] and not logic.view()["running"]
    assert not logic.choose("sobremesa") and not logic.start_run("ls", 0.0)["ok"]
    assert logic.cancel(1.0) and logic.state == ConsoleState.READY
    assert logic.outcome.text == "No se corrió: faltó la contraseña de sudo."
    assert not logic.give_password("x", 1.0)["ok"]

    logic.start_run("sudo apt update", 2.0)
    payload = logic.give_password("clave", 3.0)
    assert payload["stdin"] == b"clave\n" and "clave" not in payload["script"]
    assert "command sudo -S" in payload["script"] and logic.view()["running"]
    assert "clave" not in repr(logic.view()) and "clave" not in repr(vars(logic))


def test_folder_is_kept_per_target_and_history_records_commands():
    logic = ConsoleLogic()
    logic.set_targets([PEER, OTHER])
    assert logic.view()["prompt"] == "~"
    logic.start_run("cd Descargas", 0.0)
    logic.run_finished(True, 0, 1.0, place=Place("/home/ana/Descargas", "/home/ana"))
    assert logic.view()["prompt"] == "~/Descargas"
    assert "cd -- /home/ana/Descargas" in logic.start_run("ls", 2.0)["script"]
    logic.run_finished(True, 0, 3.0)  # sin marca: la carpeta no cambia
    assert logic.prompt == "~/Descargas"
    logic.choose("taller")
    assert logic.prompt == "~" and logic.history.items == ("cd Descargas", "ls")


def test_clear_runs_nothing_and_needs_no_target():
    logic = ConsoleLogic()
    payload = logic.start_run(" clear ", 0.0)
    assert payload["ok"] and payload["clear"] and "script" not in payload
    assert logic.state == ConsoleState.NO_TARGET and logic.history.items == ("clear",)
    logic.set_targets([PEER])
    assert logic.start_run("clear", 1.0)["clear"] and logic.state == ConsoleState.READY
    assert not logic.start_run("clear -x", 2.0).get("clear")


def test_windows_target_gets_a_powershell_script_and_no_password():
    logic = ConsoleLogic()
    logic.set_targets([PEER, OTHER], {"taller": "windows"})
    assert logic.start_run("sudo hostname", 0.0)["asking"]
    logic.cancel(0.5)
    payload = logic.start_run("hostname", 0.0)
    assert payload["ok"] and payload["script"].startswith("cd\n")
    logic.run_finished(True, 0, 1.0, place=Place("/home/ana", "/home/ana"))
    assert logic.choose("taller")
    payload = logic.start_run("sudo hostname", 2.0)
    assert not payload["asking"] and payload["stdin"] == b""
    assert payload["script"].startswith("try { Set-Location -LiteralPath $HOME ")
    logic.run_finished(True, 0, 3.0, place=Place("C:\\Users\\ana\\Desktop", "C:\\Users\\ana"))
    assert logic.prompt == "~\\Desktop"
    assert logic.start_run("cls", 4.0).get("clear")
    assert "'C:\\Users\\ana\\Desktop'" in logic.start_run("dir", 5.0)["script"]
