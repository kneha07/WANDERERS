"""survey/tiles.py: HEALPix helpers, S3 path handling (on a local fake bucket), schema unification, quality
cuts and the fixtures. No network."""
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.fs as pfs
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from survey import tiles  # noqa: E402
from test_survey_core_synth import table_from_arrays  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
KAPTEYN = FIX / "neowise_kapteyn_4arcmin.parquet"
W0855 = FIX / "neowise_wise0855_4arcmin.parquet"
CONTRACT_COLUMNS = ("source_id ra dec sigra sigdec sigradec mjd w1mpro w1sigmpro w1snr w2mpro w2sigmpro w2snr "
                    "cc_flags ph_qual nb na qual_frame qi_fact saa_sep moon_masked scan_id frame_num").split()


# ------------------------------------------------------------------------------------------- constants
def test_years_cover_the_whole_mission():
    assert tiles.YEARS[0] == "year1" and tiles.YEARS[10] == "year11" and tiles.YEARS[-1] == "addendum"
    assert len(tiles.YEARS) == 12 and len(set(tiles.YEARS)) == 12


def test_columns_match_contract():
    assert tiles.COLUMNS == CONTRACT_COLUMNS
    assert set(tiles.CORE_COLUMNS) <= set(tiles.COLUMNS)


def test_healpix_constants():
    assert tiles.NSIDE == 32 and tiles.N_TILES == 12288
    assert tiles.TILE_AREA_DEG2 == pytest.approx(3.357, abs=0.001)
    assert tiles.TILE_AREA_DEG2 * tiles.N_TILES == pytest.approx(41252.96, rel=1e-5)


# ------------------------------------------------------------------------------------------- HEALPix
def test_tile_of_known_targets():
    assert tiles.tile_of(77.95994, -45.04381) == 8545      # Kapteyn's Star
    assert tiles.tile_of(133.7864, -7.2439) == 10226       # WISE 0855-0714


def test_tile_of_scalar_and_array():
    k = tiles.tile_of(10.0, 10.0)
    assert isinstance(k, int)
    arr = tiles.tile_of(np.array([10.0, 200.0, 300.0]), np.array([10.0, -30.0, 80.0]))
    assert arr.shape == (3,) and arr.dtype == np.int64 and arr[0] == k
    assert ((arr >= 0) & (arr < tiles.N_TILES)).all()


def test_tile_of_wraps_ra():
    assert tiles.tile_of(360.0, 5.0) == tiles.tile_of(0.0, 5.0)
    assert tiles.tile_of(-10.0, 5.0) == tiles.tile_of(350.0, 5.0)


@pytest.mark.parametrize("k5", [0, 1, 1000, 4010, 6143, 8545, 10226, 12287])
def test_tile_center_round_trip(k5):
    ra, dec = tiles.tile_center(k5)
    assert 0 <= ra < 360 and -90 <= dec <= 90
    assert tiles.tile_of(ra, dec) == k5


def test_tile_corners_surround_center():
    k5 = 8545
    corners = tiles.tile_corners(k5)
    assert len(corners) == 4 and all(len(c) == 2 for c in corners)
    ra0, dec0 = tiles.tile_center(k5)
    for ra, dec in corners:
        d = np.degrees(np.arccos(np.sin(np.radians(dec)) * np.sin(np.radians(dec0)) + np.cos(np.radians(dec))
                                 * np.cos(np.radians(dec0)) * np.cos(np.radians(ra - ra0))))
        assert 0.5 < d < 2.0     # a ~1.8 deg tile


def test_tile_neighbours_are_symmetric():
    nb = tiles.tile_neighbours(8545)
    assert 7 <= len(nb) <= 8 and 8545 not in nb
    for n in nb:
        assert 8545 in tiles.tile_neighbours(n)


def test_tile_path_layout():
    p = tiles.tile_path(8545, "year3")
    assert p == ("nasa-irsa-wise/wise/neowiser/catalogs/p1bs_psd/healpix_k5/year3/neowiser-healpix_k5-year3.parquet/"
                 "healpix_k0=8/healpix_k5=8545/part0.snappy.parquet")
    assert tiles.tile_path(9386, "addendum", part=12).endswith("healpix_k0=9/healpix_k5=9386/part12.snappy.parquet")


# ------------------------------------------------------------------------------------------- reading
@pytest.fixture()
def fake_bucket(tmp_path):
    """A local filesystem laid out like the S3 bucket, with tile 8545 year1 (2 parts) and year2."""
    fs = pfs.SubTreeFileSystem(str(tmp_path), pfs.LocalFileSystem())
    t = table_from_arrays(np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([56700.0, 56700.1]),
                          np.array([0.1, 0.1]), np.array([12.0, 12.1]), np.array([11.0, 11.1]), nonnull=True)
    for year, part in (("year1", 0), ("year1", 1), ("year2", 0)):
        path = tmp_path / tiles.tile_path(8545, year, part)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(t, str(path))
    return fs


def test_read_tile_year_from_bucket_layout(fake_bucket):
    t = tiles.read_tile_year(8545, "year1", fs=fake_bucket)
    assert t.num_rows == 2 and t.column_names == tiles.COLUMNS
    assert all(f.nullable for f in t.schema)


def test_read_tile_year_columns(fake_bucket):
    t = tiles.read_tile_year(8545, "year2", fs=fake_bucket, columns=["ra", "dec", "mjd"])
    assert t.column_names == ["ra", "dec", "mjd"]


def test_read_tile_year_missing_returns_none(fake_bucket):
    assert tiles.read_tile_year(8545, "addendum", fs=fake_bucket) is None
    assert tiles.read_tile_year(1, "year1", fs=fake_bucket) is None


def test_read_tile_year_other_part(fake_bucket):
    assert tiles.read_tile_year(8545, "year1", fs=fake_bucket, part=1).num_rows == 2
    assert tiles.read_tile_year(8545, "year1", fs=fake_bucket, part=2) is None


def test_iter_tile_year_by_row_group(tmp_path):
    fs = pfs.SubTreeFileSystem(str(tmp_path), pfs.LocalFileSystem())
    n = 10
    t = table_from_arrays(np.arange(n, dtype=float), np.zeros(n), np.full(n, 56700.0), np.full(n, 0.1),
                          np.full(n, 12.0), np.full(n, 11.0), nonnull=True)
    path = tmp_path / tiles.tile_path(9386, "year1")
    path.parent.mkdir(parents=True)
    pq.write_table(t, str(path), row_group_size=4)          # 3 row groups, like the 6 M-row pole files
    pieces = list(tiles.iter_tile_year(9386, "year1", fs=fs, columns=["ra", "mjd"]))
    assert [p.num_rows for p in pieces] == [4, 4, 2]
    assert all(p.column_names == ["ra", "mjd"] and all(f.nullable for f in p.schema) for p in pieces)
    assert sum((p["ra"].to_pylist() for p in pieces), []) == list(range(n))
    assert list(tiles.iter_tile_year(9386, "year2", fs=fs)) == []          # missing file: nothing


def test_tile_year_parts(fake_bucket):
    assert tiles.tile_year_parts(8545, "year1", fs=fake_bucket) == 2
    assert tiles.tile_year_parts(8545, "year2", fs=fake_bucket) == 1
    assert tiles.tile_year_parts(8545, "year5", fs=fake_bucket) == 0


def test_s3_filesystem_is_cached_per_process():
    assert tiles.s3() is tiles.s3()


# ------------------------------------------------------------------------------------------- schemas
def test_nullable_makes_every_field_nullable():
    t = table_from_arrays([1.0], [2.0], [56700.0], [0.1], [12.0], [11.0], nonnull=True)
    assert not any(f.nullable for f in t.schema)
    u = tiles.nullable(t)
    assert all(f.nullable for f in u.schema)
    assert u["ra"].to_pylist() == [1.0] and u.num_rows == 1


def test_concat_tables_mixed_nullability():
    a = table_from_arrays([1.0], [2.0], [56700.0], [0.1], [12.0], [11.0], nonnull=True)
    b = table_from_arrays([3.0, 4.0], [2.0, 2.0], [56900.0, 56900.0], [0.1, 0.1], [12.0, 12.0], [11.0, 11.0])
    with pytest.raises((pa.ArrowInvalid, pa.ArrowTypeError)):
        pa.concat_tables([a, b])            # what the raw years do without unification
    c = tiles.concat_tables([a, None, b])
    assert c.num_rows == 3 and c["ra"].to_pylist() == [1.0, 3.0, 4.0]


def test_concat_tables_promotes_types():
    a = pa.table({"nb": pa.array([1], pa.int32())})
    b = pa.table({"nb": pa.array([2], pa.int64())})
    c = tiles.concat_tables([a, b])
    assert c["nb"].to_pylist() == [1, 2]


def test_concat_tables_all_missing():
    assert tiles.concat_tables([None, None]) is None


# ------------------------------------------------------------------------------------------- fixtures
def test_read_fixture_kapteyn():
    t = tiles.read_fixture(KAPTEYN)
    assert t.num_rows == 86209 and t.column_names == tiles.COLUMNS
    assert all(f.nullable for f in t.schema)


def test_read_fixture_columns():
    t = tiles.read_fixture(W0855, columns=["ra", "dec", "mjd"])
    assert t.column_names == ["ra", "dec", "mjd"] and t.num_rows == 60408


def test_year_of_mjd():
    y = tiles.year_of_mjd([56640.0, 56639.0 + 365.25 + 1, 60300.0, 60700.0])
    assert list(y) == ["year1", "year2", "year11", "addendum"]


def test_fixture_reader_splits_years():
    reader = tiles.fixture_reader(KAPTEYN, missing=("year3",))
    parts = [reader(8545, y) for y in tiles.YEARS]
    assert parts[2] is None                                  # explicitly missing
    assert parts[-1] is None                                 # no addendum rows in the fixture
    total = sum(p.num_rows for p in parts if p is not None)
    full = tiles.fixture_reader(KAPTEYN)
    assert total + full(8545, "year3").num_rows == 86209
    for y, p in zip(tiles.YEARS, parts):
        if p is not None:
            assert set(tiles.year_of_mjd(p["mjd"].to_numpy())) == {y}


# ------------------------------------------------------------------------------------------- quality mask
def _one(**over):
    return table_from_arrays([10.0], [10.0], [56700.0], [0.2], [12.0], [11.0], **over)


def test_good_mask_clean_row():
    assert tiles.good_mask(_one()).tolist() == [True]


@pytest.mark.parametrize("over", [
    {"cc_flags": ["D000"]},                 # W1 diffraction spike
    {"cc_flags": ["0P00"]},                 # W2 persistence (latent)
    {"cc_flags": ["h000"]},                 # possible halo (lower case still flagged)
    {"cc_flags": ["0o00"]},                 # possible ghost in W2
    {"moon_masked": ["01"]},                # W2 in the moon mask
    {"qual_frame": [0]},                    # bad frame
    {"saa_sep": [-3.0]},                    # inside the SAA
    {"saa_sep": [0.0]},
    {"nb": [3]},                            # deep blend
    {"w1snr": [4.9], "w2snr": [4.0]},       # not a real detection
    {"sigra": [float("nan")]},
    {"sigdec": [0.0]},
])
def test_good_mask_each_cut(over):
    assert tiles.good_mask(_one(**over)).tolist() == [False]


@pytest.mark.parametrize("over", [
    {"cc_flags": ["00D0"]},                 # a W3 flag does not matter for W1/W2 astrometry
    {"w1snr": [2.0], "w2snr": [6.0]},       # W2-only detection (cold brown dwarfs)
    {"w1snr": [6.0], "w2snr": [None]},      # W1-only detection
    {"moon_masked": ["0010"[:2]]},
    {"nb": [2]},
])
def test_good_mask_keeps(over):
    assert tiles.good_mask(_one(**over)).tolist() == [True]


def test_good_mask_nulls_are_bad():
    assert tiles.good_mask(_one(cc_flags=pa.array([None], pa.string()))).tolist() == [False]
    assert tiles.good_mask(_one(qual_frame=pa.array([None], pa.int64()))).tolist() == [False]


def test_good_mask_empty_table():
    t = table_from_arrays([], [], [], [], [], [])
    assert tiles.good_mask(t).shape == (0,)


def test_good_mask_on_real_fixture_keeps_kapteyn():
    t = tiles.read_fixture(KAPTEYN)
    m = tiles.good_mask(t)
    assert m.dtype == bool and len(m) == t.num_rows
    assert 0.1 < m.mean() < 0.5
    # Kapteyn's own detections (W2 ~ 4 in NEOWISE photometry) survive in every visit
    w2 = t["w2mpro"].to_numpy(zero_copy_only=False).astype(float)
    bright = (w2 < 5.0) & m
    assert bright.sum() > 300
