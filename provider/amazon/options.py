"""Documented Amazon Mexico search refinement options."""

from enum import Enum


class Seller(Enum):
    """Amazon seller refinement identifiers used by generated search URLs."""

    none = ""
    amazon_mx = "AVDBXBAVVSXLQ"
    amazon_usa = "A1G99GVHAT2WD8"
    amazon_remates = "A23KQ2J0V65IPS"
    buyspry = "A37VHTD60S0G3C"
    randu_mx = "A38E0DZZJWNMAA"
    v_i_v_o = "AX105E1SOBX1B"
    ugreen_group_limited = "AKXVBT49GGF3B"


class Brand(Enum):
    """Amazon Marca refinement identifiers documented for generated searches."""

    apple = "110955"
    nintendo = "218247"
