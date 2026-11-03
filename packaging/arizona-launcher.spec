Name:           arizona-launcher
Version:        %{pkg_version}
Release:        1%{?dist}
Summary:        Unofficial Arizona RP / Rodina RP launcher for Linux
License:        MIT
URL:            https://github.com/alinaz18/arizona-launcher-linux
Source0:        arizona-launcher-%{version}.tar.gz
BuildArch:      noarch

Requires:       python3 >= 3.9
Requires:       python3-pyside6
Requires:       wine
Recommends:     winetricks
Recommends:     cabextract

%description
Native Qt launcher for Arizona RP, Rodina RP and Village Life: server list,
game install, updates and repair from the official servers, mod catalog and
news. The Windows game itself runs through a Wine prefix managed by the
launcher. Not affiliated with Arizona Games.

%prep
%setup -q

%build

%install
bash packaging/stage.sh %{buildroot} %{_prefix}

%files
%license %{_datadir}/licenses/arizona-launcher/LICENSE
%doc %{_datadir}/doc/arizona-launcher/README.md
%doc %{_datadir}/doc/arizona-launcher/README.en.md
%{_bindir}/arizona-launcher
%{_datadir}/arizona-launcher/
%{_datadir}/applications/arizona-launcher.desktop
%{_datadir}/icons/hicolor/scalable/apps/arizona-launcher.svg
