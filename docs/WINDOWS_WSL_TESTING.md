# Windows·Linux 로컬 테스트 (맥 옆의 Windows 머신 + WSL)

GitHub Actions는 비용 때문에 수동 실행만 합니다(`AGENTS.md`, 개발 이력 2.3). 그 대신 맥 옆의 Windows 머신에서
**Windows(Python 3.10, 3.13)**와 **WSL의 Linux(Python 3.10, 3.13)** 테스트를 맥에서 명령 하나로 돌립니다.
설계 경과와 리뷰 내용은 개발 이력 2.4절에 있습니다.

```bash
scripts/remote_test.sh            # HEAD를 검증
scripts/remote_test.sh <커밋|브랜치>
```

## 동작 방식
1. 맥이 저장소를 `git bundle`(약 1 MB)로 묶어 `scp`로 Windows의 `~\coat-test\`에 보냅니다. Windows에는 GitHub 권한이 필요 없습니다.
2. `ssh`로 `win_test.ps1`을 실행합니다. 커밋을 새 폴더에 받아 Windows py3.10 → py3.13 순서로 테스트합니다.
3. 이어서 `wsl.exe`로 `linux_test.sh`를 실행합니다. WSL은 bundle에서 직접 받아(줄바꿈 변환 없음) Linux 파일 시스템에서 py3.10 → py3.13을 돌립니다.
4. 결과(`summary.txt`, 환경별 로그, JUnit XML, 패키지 버전)를 맥의 `remote-test-results/<커밋>/`로 가져옵니다.

**판정**: 네 환경 모두 종료 코드 0, 테스트 1개 이상, **건너뛴 테스트 0개**여야 통과입니다. PySide6를 불러오지 못하면
`tests/test_gui_smoke.py`가 통째로 건너뛰어도 pytest는 성공으로 끝나기 때문입니다. `PYTHONUTF8`은 켜지 않습니다
(켜면 인코딩을 지정하지 않은 파일 읽기 버그가 가려짐). 가상환경은 실행 사이에 재사용하고, 매번 프로젝트와 최신 휠을 다시 설치합니다(CI와 같음).

## 보안 원칙
SSH 서버를 켜는 것이라 다음을 지킵니다. `setup_sshd.ps1`이 설정하고, `win_test.ps1`이 실행할 때마다 확인해 어긋나면 경고합니다.

| 대비 | 이유 |
|---|---|
| **키 로그인만** (`PasswordAuthentication no`) | Windows OpenSSH는 기본으로 비밀번호 로그인을 허용합니다. 같은 네트워크의 기기가 비밀번호를 대입할 수 없게 합니다. |
| **방화벽: 맥의 IP만, 개인 네트워크에서만** | 같은 Wi-Fi의 다른 기기, 공용 네트워크에서의 접속을 막습니다. |
| **로그인 계정 하나** (`AllowUsers`) | 다른 계정으로는 들어올 수 없습니다. |
| **sshd 수동 시작** | 테스트할 때만 켜고, 평소에는 열린 포트가 없습니다. |
| **공유기에 22번 포트 포워딩 없음** (가능하면 UPnP 끄기) | 인터넷에서 닿지 않게 합니다. 공유기 관리 화면에서 직접 확인합니다. |
| **맥의 개인 키에 암호** (키체인에 저장) | 키 파일이 유출되어도 바로 쓸 수 없습니다. |

맥의 IP가 바뀌면 방화벽이 막으므로, 공유기에서 맥에 **고정 IP(DHCP 예약)**를 주는 것이 좋습니다.

## 1회 설정
### 맥
```bash
ssh-keygen -t ed25519 -f ~/.ssh/coat_win -C coat-win     # 암호(passphrase)를 꼭 넣습니다
ssh-add --apple-use-keychain ~/.ssh/coat_win
cat ~/.ssh/coat_win.pub                                    # Windows 설정에 붙여 넣을 공개키
ipconfig getifaddr en0                                     # 맥의 IP (Wi-Fi). 유선이면 en1 등
```
`~/.ssh/config`에 추가합니다(`<...>`는 실제 값으로):
```
Host coat-win
    HostName <Windows IP>
    User <Windows 사용자 이름>
    IdentityFile ~/.ssh/coat_win
    IdentitiesOnly yes
    UseKeychain yes
    AddKeysToAgent yes
    BatchMode yes
    ConnectTimeout 5
```

### Windows (관리자 PowerShell)
아직 SSH가 없으므로 1회 설정 파일 두 개(`scripts/remote/setup_sshd.ps1`, `scripts/remote/bootstrap_wsl.sh`)는 GitHub 웹 화면에서
받거나 USB 등으로 Windows의 `%USERPROFILE%\coat-test\`에 옮겨 둡니다.

1. `setup_sshd.ps1`을 **내용을 읽은 뒤** 실행합니다. `-User`는 맥이 로그인할 계정(그 계정의 WSL에서 Linux 테스트가 돎)이며 필수입니다.
   다른 관리자 계정의 자격 증명으로 승격한 PowerShell에서는 `$env:USERNAME`이 그 관리자 계정이 되기 때문입니다.
   ```powershell
   cd $env:USERPROFILE\coat-test
   powershell -ExecutionPolicy Bypass -File setup_sshd.ps1 -User <계정> -MacIp <맥 IP> -PublicKey "<coat_win.pub 한 줄>"
   ```
   OpenSSH Server 설치, 수동 시작(끝나면 꺼 둠), 키 로그인만, `AllowUsers`, 방화벽(맥 IP·개인 네트워크), 공개키 등록을 합니다.
   - 관리자 계정이면 키는 `C:\ProgramData\ssh\administrators_authorized_keys`에 들어갑니다. 기본 `sshd_config`의
     `Match Group administrators`가 관리자에게는 이 파일만 읽게 하므로, 판별은 SID로 합니다(틀리면 비밀번호도 꺼진 채 로그인 불가).
   - 파일은 BOM 없는 UTF-8, 소유자(와 SYSTEM)만 읽기로 저장합니다(UTF-16이거나 권한이 넓으면 sshd가 키를 무시).
   - 원래 `sshd_config`는 `sshd_config.bak-<시각>`으로 남고, 새 설정이 `sshd -t` 검사를 통과하지 못하면 되돌립니다.
     맥이 로그인하지 못하면 스크립트가 마지막에 출력한 `Copy-Item` 명령으로 되돌린 뒤 원인을 봅니다.
   - 계정 이름에 공백이 있으면 거부합니다(`AllowUsers`는 공백으로 이름을 나눔).
2. 설정 → 네트워크에서 집 네트워크가 **개인**인지 확인합니다(공용이면 방화벽 규칙이 적용되지 않아 맥도 못 들어옵니다).
3. Git과 uv를 설치하고 Python을 받아 둡니다(일반 PowerShell):
   ```powershell
   winget install --id Git.Git -e
   winget install --id astral-sh.uv -e
   # 새 PowerShell 창에서
   uv python install 3.10 3.13
   ```

### WSL
WSL 터미널에서 옮겨 둔 `bootstrap_wsl.sh`를 실행합니다(sudo 암호를 묻습니다):
`bash /mnt/c/Users/<Windows 사용자 폴더>/coat-test/bootstrap_wsl.sh`. git, Qt 실행 라이브러리,
한글 글꼴(`fonts-nanum`), uv, Python 3.10·3.13을 설치합니다. 배포판 이름이 `Ubuntu`가 아니면 맥에서
`COAT_TEST_DISTRO=<이름>`을 줍니다(`wsl -l -v`로 확인).

### 설정 확인 (처음 한 번)
Windows 관리자 PowerShell에서 `Start-Service sshd`를 한 뒤, 맥에서:
```bash
ssh coat-win whoami                                         # 암호 없이 사용자 이름이 나와야 함
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password -o BatchMode=no coat-win
                                                            # 반드시 거부되어야 함 (Permission denied)
ssh coat-win wsl.exe -d Ubuntu -e uname -a                  # WSL이 SSH 세션에서 뜨는지
```
마지막 명령은 **Windows를 재부팅한 직후**에도 한 번 확인합니다. 키 로그인 SSH 세션에서는 `wsl.exe`가 로그온 세션 오류
(`0x80070520`)로 뜨지 않는 사례가 있다고 합니다(미실측). 그러면 아래 "문제 해결"을 봅니다.

## 매번 하는 일
1. Windows 관리자 PowerShell: `Start-Service sshd`
2. 맥: `scripts/remote_test.sh` (첫 실행은 휠을 내려받느라 몇 분 걸립니다. Claude Code에서는 백그라운드로 돌립니다.)
3. Windows 관리자 PowerShell: `Stop-Service sshd`

## 문제 해결
- **`cannot reach coat-win`**: sshd가 꺼져 있거나, 맥 IP가 바뀌었거나, 네트워크가 공용으로 바뀌었습니다.
- **`wsl.exe exited with …`** (요약의 warning): SSH 세션에서 WSL을 띄우지 못한 것입니다. 대안은 WSL 안에 sshd를 따로 두고
  맥에서 직접 접속하는 것입니다(같은 보안 원칙 적용). 이 경우 이 문서와 스크립트를 고칩니다.
- **`missing packages`** (linux warning): WSL에서 `bootstrap_wsl.sh`를 다시 실행합니다. 맥에서
  `scp scripts/remote/bootstrap_wsl.sh coat-win:coat-test/`로 최신 판을 보낼 수 있습니다.
- **결과를 가져오지 못함** (종료 코드 4): 원격 실행은 끝났지만 맥에 증거가 없으므로 통과로 치지 않습니다. 다시 실행합니다.
- **스크립트를 고칠 때**: `.ps1`은 ASCII만 씁니다(PowerShell 5.1이 BOM 없는 파일을 ANSI 코드 페이지로 읽음). `.sh`는 LF 줄바꿈입니다.
  `tests/test_remote_scripts.py`가 둘 다 확인합니다.
- **건너뛴 테스트가 있음**: 보통 PySide6를 불러오지 못한 것입니다. `linux-<py>.log` / `win-<py>.log`의 skip 사유(`-rs`)를 봅니다.
