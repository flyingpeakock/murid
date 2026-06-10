{
  python3Packages,
  lib,
}:
python3Packages.buildPythonApplication (finalAttrs: {
  pname = "HardcoverHarvester";
  version = "0.0.0";
  format = "pyproject";
  dependencies = with python3Packages; [
    hatchling
    hatch-vcs
    rich-argparse
  ];

  src = builtins.path {
    path = ./.;
    name = finalAttrs.pname;
  };

  meta = {
    description = "Search for books from Hardcover on MaM and add them to calibre";
    homepage = "https://git.phlipphlop.me/phlipphlop/HardcoverHarvester";
    platforms = lib.platforms.all;
    mainProgram = "HardcoverHarvester";
    license = lib.licenses.mit;
  };
})
