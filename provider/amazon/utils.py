from enum import Enum


class Seller(Enum):
    none = ""
    amazon_mx = "AVDBXBAVVSXLQ"
    amazon_usa = "A1G99GVHAT2WD8"
    amazon_remates = "A23KQ2J0V65IPS"
    buyspry = "A37VHTD60S0G3C"

    @property
    def filter_query(self) -> str:
        """Returns the URL parameter for filtering by seller if one exists."""
        if self != Seller.none:
            return f"&rh=p_6%3A{self.value}"
        return ""
