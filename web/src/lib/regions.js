/* Region registry and workload presets.
 *
 * Annual means are approximate published operational averages (Ember, system
 * operators). They set the level for the transferred forecast, and they are
 * deliberately easy to override. See the limitations section of the README.
 */

export const REGIONS = {
  GB:    { name: "Great Britain",         lat: 54.0,  lon: -2.0,   mean: 124, official: true },
  FR:    { name: "France",                lat: 46.8,  lon: 2.4,    mean: 56 },
  DE:    { name: "Germany",               lat: 51.2,  lon: 10.4,   mean: 381 },
  ES:    { name: "Spain",                 lat: 40.4,  lon: -3.7,   mean: 150 },
  PL:    { name: "Poland",                lat: 52.2,  lon: 19.1,   mean: 662 },
  IE:    { name: "Ireland",               lat: 53.3,  lon: -7.7,   mean: 320 },
  CAISO: { name: "California (CAISO)",    lat: 36.8,  lon: -119.4, mean: 240 },
  ERCOT: { name: "Texas (ERCOT)",         lat: 31.0,  lon: -99.0,  mean: 400 },
  PJM:   { name: "US Mid-Atlantic (PJM)", lat: 39.8,  lon: -77.5,  mean: 350 },
  NYISO: { name: "New York (NYISO)",      lat: 42.9,  lon: -75.5,  mean: 210 },
  IN:    { name: "India",                 lat: 21.0,  lon: 79.0,   mean: 713 },
  AU:    { name: "Australia (NEM)",       lat: -33.0, lon: 147.0,  mean: 550 },
  JP:    { name: "Japan",                 lat: 36.2,  lon: 138.3,  mean: 490 },
  BR:    { name: "Brazil",                lat: -14.0, lon: -51.0,  mean: 120 },
};

export const PRESETS = {
  ev:         { label: "EV charge",         hours: 6, kw: 7.0,  split: true,  block: 1, deadline: 14 },
  training:   { label: "ML training run",   hours: 4, kw: 0.7,  split: false, block: 1, deadline: 24 },
  dishwasher: { label: "Dishwasher",        hours: 2, kw: 1.2,  split: false, block: 1, deadline: 12 },
  batch:      { label: "Data-centre batch", hours: 8, kw: 50.0, split: true,  block: 2, deadline: 48 },
  heating:    { label: "Water heating",     hours: 3, kw: 3.0,  split: true,  block: 1, deadline: 12 },
};

export const TIER_COPY = {
  official: "Published by the grid operator.",
  modelled: "GridShift model on live weather.",
  transferred: "Model transferred from Great Britain and level-calibrated.",
};
