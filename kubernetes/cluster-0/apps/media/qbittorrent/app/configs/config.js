// Torrent content layout: Original
// Default Torrent Management Mode: Automatic
// Default Save Path: /media/qb/downloads
// External program on finished: /scripts/xseed.sh "%F"

module.exports = {
  delay: 30,
  qbittorrentUrl: "http://localhost:80",

  torznab: [
    "http://prowlarr.media.svc.cluster.local:80/13/api?apikey={{ .api_key }}", // tl
    "http://prowlarr.media.svc.cluster.local:80/7/api?apikey={{ .api_key }}", // fl
    "http://prowlarr.media.svc.cluster.local:80/6/api?apikey={{ .api_key }}", // st
    "http://prowlarr.media.svc.cluster.local:80/8/api?apikey={{ .api_key }}", // blu
    "http://prowlarr.media.svc.cluster.local:80/3/api?apikey={{ .api_key }}", // btn
    "http://prowlarr.media.svc.cluster.local:80/5/api?apikey={{ .api_key }}", // or
    "http://prowlarr.media.svc.cluster.local:80/14/api?apikey={{ .api_key }}", // mtv
    "http://prowlarr.media.svc.cluster.local:80/15/api?apikey={{ .api_key }}", // ant
  ],

  action: "inject",
  includeEpisodes: true,
  includeNonVideos: true,
  duplicateCategories: true,

  matchMode: "safe",
  skipRecheck: true,
  linkType: "symlink",
  linkDir: "/media/qb/downloads/xseeds",

  // I have sonarr, radarr, and prowlarr categories set in qBittorrent
  // The save paths for them are set to the following:
  dataDirs: [
    "/media/qb/downloads/sonarr",
    "/media/qb/downloads/radarr",
    "/media/qb/downloads/prowlarr",
  ],

  outputDir: "/config/xseeds",
  torrentDir: "/config/qBittorrent/BT_backup",
};
