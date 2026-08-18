// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

interface IAllegiancePass {
    function ownerOf(uint256 tokenId) external view returns (address owner);
    function sentinelBurn(uint256 tokenId) external returns(bool);
}