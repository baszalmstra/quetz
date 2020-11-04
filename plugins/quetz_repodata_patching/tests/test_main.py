import json
import os
import uuid
from unittest import mock

import pytest

import quetz
from quetz import indexing
from quetz.db_models import Channel, Package, Profile, User


@pytest.fixture
def user(db):
    user = User(id=uuid.uuid4().bytes, username="bartosz")
    profile = Profile(name="Bartosz", avatar_url="http:///avatar", user=user)
    db.add(user)
    db.add(profile)
    db.commit()
    yield user


@pytest.fixture
def channel_name():
    return "my-channel"


@pytest.fixture
def package_name():
    return "mytestpackage"


@pytest.fixture
def package_file_name(package_name):
    return f"{package_name}-0.1-0.tar.bz"


@pytest.fixture
def channel(dao: "quetz.dao.Dao", channel_name, user):

    channel_data = Channel(name=channel_name, private=False)
    channel = dao.create_channel(channel_data, user.id, "owner")
    return channel


@pytest.fixture
def package_version(
    dao: "quetz.dao.Dao", user, channel, package_name, db, package_file_name
):
    package_data = Package(name=package_name)

    dao.create_package(channel.name, package_data, user.id, "owner")
    package_format = 'tarbz2'
    package_info = '{"run_exports": {"weak": ["otherpackage > 0.1"]}, "size": 100}'
    version = dao.create_version(
        channel.name,
        package_name,
        package_format,
        "noarch",
        "0.1",
        "0",
        "0",
        package_file_name,
        package_info,
        user.id,
    )

    yield version


@pytest.fixture
def repodata_name(channel):
    package_name = f"{channel.name}-repodata-patches"
    return package_name


@pytest.fixture
def repodata_file_name(repodata_name):
    version = "0.1"
    build_str = "0"
    return f"{repodata_name}-{version}-{build_str}.tar.bz2"


@pytest.fixture
def patch_content(package_file_name):
    return {
        "packages": {
            package_file_name: {"run_exports": {"weak": ["otherpackage > 0.2"]}}
        }
    }


@pytest.fixture
def repodata_archive(repodata_file_name, patch_content):

    import tarfile
    import time
    from io import BytesIO

    tar_content = BytesIO()
    tar = tarfile.open(repodata_file_name, "w|bz2", fileobj=tar_content)

    patch_instructions = BytesIO(json.dumps(patch_content).encode('ascii'))

    info = tarfile.TarInfo(name='noarch')
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.mtime = time.time()
    tar.addfile(tarinfo=info)

    info = tarfile.TarInfo(name='noarch/patch_instructions.json')
    info.size = len(patch_instructions.getvalue())
    info.mtime = time.time()
    tar.addfile(tarinfo=info, fileobj=patch_instructions)
    tar.close()
    tar_content.seek(0)
    yield tar_content


@pytest.fixture
def package_repodata_patches(
    dao: "quetz.dao.Dao",
    user,
    channel,
    db,
    pkgstore,
    repodata_name,
    repodata_file_name,
    repodata_archive,
):

    package_name = repodata_name
    package_data = Package(name=package_name)

    dao.create_package(channel.name, package_data, user.id, "owner")
    package_format = 'tarbz2'
    package_info = '{"size": 100}'
    version = dao.create_version(
        channel.name,
        package_name,
        package_format,
        "noarch",
        "0.1",
        "0",
        "0",
        repodata_file_name,
        package_info,
        user.id,
    )

    pkgstore.add_package(repodata_archive, channel.name, f"noarch/{repodata_file_name}")

    return version


@pytest.fixture
def pkgstore(config):
    pkgstore = config.get_package_store()
    return pkgstore


@pytest.mark.parametrize("repodata_stem", ["repodata", "current_repodata"])
def test_post_package_indexing(
    pkgstore,
    dao,
    package_version,
    channel_name,
    package_repodata_patches,
    db,
    package_file_name,
    repodata_stem,
):
    def get_db():
        yield db

    with mock.patch("quetz_repodata_patching.main.get_db", get_db):
        indexing.update_indexes(dao, pkgstore, channel_name)

    repodata_path = os.path.join(
        pkgstore.channels_dir, channel_name, "noarch", f"{repodata_stem}.json"
    )
    assert os.path.isfile(repodata_path)
    with open(repodata_path) as fid:
        data = json.load(fid)
    assert data['packages'][package_file_name]['run_exports'] == {
        "weak": ["otherpackage > 0.2"]
    }

    orig_repodata_path = os.path.join(
        pkgstore.channels_dir,
        channel_name,
        "noarch",
        f"{repodata_stem}_from_packages.json",
    )

    assert os.path.isfile(orig_repodata_path)
    with open(orig_repodata_path) as fid:
        data = json.load(fid)
    assert data['packages'][package_file_name]['run_exports'] == {
        "weak": ["otherpackage > 0.1"]
    }
