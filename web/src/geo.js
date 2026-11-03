// Geography of the pilot. Coordinates of streets/settlements come from Mapbox geocoding
// (Ushcheva st., Zarechny, Kozhevenny proezd). Exact dam alignments are NOT public:
// segment lines below are approximate and must be replaced with the akimat's survey data.
export const CITY_CENTER = [69.1587, 54.8672];

export const SEGMENTS = {
  PODG: { name: "Дамба ул. Ущева", area: "Подгора", line: [[69.1105, 54.8825], [69.1172, 54.8808], [69.1245, 54.8796]] },
  KOZH: { name: "Обвалование Кожевенный", area: "Кожевенный", line: [[69.0640, 54.8850], [69.0691, 54.8835], [69.0750, 54.8822]] },
  RECH: { name: "Вал объездной дороги", area: "Речпорт", line: [[69.0860, 54.8890], [69.0930, 54.8872], [69.1000, 54.8858]] },
  ZAR: { name: "Обвалование Заречный", area: "Заречный", line: [[69.1120, 54.9000], [69.1191, 54.9023], [69.1265, 54.9035]] },
};

export const STATIONS = {
  "PTR-ESIL-01": { coord: [69.1190, 54.8840], kind: "water" },
  "PTR-ESIL-02": { coord: [69.0950, 54.8905], kind: "water" },
  "PTR-SNOW-01": { coord: [69.2150, 54.8400], kind: "snow" },
  "PTR-SNOW-02": { coord: [69.0300, 54.8450], kind: "snow" },
};

export const mid = (line) => line[Math.floor(line.length / 2)];
